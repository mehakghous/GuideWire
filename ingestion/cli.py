"""Command line entry point.

  python -m ingestion.cli written instructions.txt --app blender -o steps.json
  python -m ingestion.cli video https://www.youtube.com/watch?v=XXXXXXXXXXX -o steps.json

Needs GEMINI_API_KEY (and YOUTUBE_API_KEY for video metadata) in the environment or .env.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from .extract import ExtractionError, extract_from_text, extract_from_video
from .providers.gemini import GeminiProvider
from .youtube.metadata import fetch_metadata, parse_video_id


def _offline(args) -> int:
    """Commands that never touch the network or a model."""
    from .router import route

    if args.cmd == "purge":
        from .retention import purge_derived
        from .youtube.captions import ROOT
        removed = purge_derived(ROOT)
        print(f"removed {len(removed)} file(s) older than 30 days", *removed, sep="\n  ")
        return 0
    if args.cmd == "captions":
        from .youtube.captions import CaptionsUnavailable, fetch_captions, purge_expired
        from .youtube.metadata import parse_video_id
        if args.purge:
            print("removed:", purge_expired())
            return 0
        try:
            res = fetch_captions(parse_video_id(args.video))
        except CaptionsUnavailable as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"captions: {res.source} ({res.language}), from_cache={res.from_cache}, tracks={res.tracks}", file=sys.stderr)
        b = route(res.text, version=args.version, input_type="transcript", duration_s=args.duration)
        print(b.model_dump_json(indent=2))
        return 0
    if args.cmd == "chat":
        from .service import Service, chat
        svc = Service.open(args.session, version=args.version, use_kb=not args.no_kb)
        if args.script:
            lines = Path(args.script).read_text(encoding="utf-8").splitlines()
        elif sys.stdin.isatty():
            print("GuideWire chat. Ask a question, paste steps, or /help. /quit to leave.", file=sys.stderr)
            lines = iter(lambda: input("> "), None)
        else:
            lines = sys.stdin
        try:
            return chat(svc, lines, as_json=args.json)
        except (EOFError, KeyboardInterrupt):
            return 0
    if args.cmd == "find":
        from .tutorials import discover, load_index, verify_captions
        entries = load_index(args.index) if args.index else load_index()
        if args.candidates:
            entries = entries + load_index(Path(__file__).resolve().parents[1] / "knowledge" / "tutorial_index_candidates.json")
        d = discover(args.text, entries, args.version, limit=args.limit)
        log = []
        if args.verify_captions and d.recommendations:
            from .youtube import api
            log = verify_captions(d.recommendations, api.caption_tracks, max_checks=args.verify_captions)
            log.append(f"about {50 * min(args.verify_captions, len(d.recommendations))} quota units used")
        print(json.dumps({"constraints": {"version": d.want.version, "level": d.want.level, "max_duration_s": d.want.max_duration_s, "topic": d.want.topic},
                          "results": [r.model_dump() for r in d.recommendations], "notes": d.notes, "excluded": d.excluded, "caption_check": log}, indent=1))
        return 0
    if args.cmd == "playlist":
        from .handoff import classify_url
        from .tutorials import playlist_recommendations
        from .youtube import api
        info = classify_url(args.url)
        pid = info.playlist_id
        if not pid:
            print("error: no playlist id in that link", file=sys.stderr)
            return 2
        try:
            items = api.playlist_items(pid)
            meta = api.videos_metadata([i["video_id"] for i in items if i["available"]])
        except api.YouTubeApiError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        recs, skipped = playlist_recommendations(items, meta, pid)
        print(json.dumps({"playlist": pid, "videos": [r.model_dump() for r in recs], "unavailable": skipped, "quota_units_used": 2}, indent=1))
        return 0
    if args.cmd == "ask":
        obs = None
        if args.mode or args.selected:
            obs = {}
            if args.mode:
                obs["mode"] = args.mode
            if args.selected:
                obs["selected_objects"] = [x.strip() for x in args.selected.split(",") if x.strip()]
        kb = tut = None
        if not args.no_kb:
            from .kb.index import DEFAULT_DB, KnowledgeBase
            from .tutorials import load_index
            db = Path(args.kb) if args.kb else DEFAULT_DB
            if db.exists():
                kb, tut = KnowledgeBase(db), load_index()
        b = route(args.text, version=args.version, observed=obs, kb=kb, tutorials=tut)
    elif args.cmd == "transcript":
        b = route(Path(args.file).read_text(encoding="utf-8"), version=args.version, input_type="transcript", duration_s=args.duration)
    else:
        b = route(Path(args.file).read_text(encoding="utf-8"), version=args.version, input_type="manual_steps")
    out = b.model_dump_json(indent=2)
    if getattr(args, "out", None):
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"route={b.route} kind={b.kind} steps={len(b.steps.steps) if b.steps else 0} api_calls={b.api_calls}; wrote {args.out}")
    else:
        print(out)
    return 0


OFFLINE_COMMANDS = ("purge", "ask", "transcript", "validate", "captions", "playlist", "find", "chat")


def _one_line(e: BaseException) -> str:
    """A bad file, bad JSON or a rejected step list as ONE readable line (no traceback, no multi-page pydantic dump)."""
    if isinstance(e, FileNotFoundError):
        return f"file not found: {e.filename or e}"
    if isinstance(e, json.JSONDecodeError):
        return f"not valid JSON ({e.msg} at line {e.lineno}, column {e.colno})"
    first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return first[:300]


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="ingestion")
    ap.add_argument("--debug", action="store_true", help="show the full traceback instead of a one-line error")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("written", help="convert written instructions (a text file) to steps")
    w.add_argument("file")
    v = sub.add_parser("video", help="convert a public YouTube tutorial to steps")
    v.add_argument("url")
    v.add_argument("--no-metadata", action="store_true", help="skip YouTube Data API call")
    a = sub.add_parser("ask", help="OFFLINE: answer a request from the catalog / parsers; never calls a model")
    a.add_argument("text")
    a.add_argument("--version", help="your Blender version, e.g. 2.80")
    a.add_argument("--mode", help="observed mode, e.g. OBJECT or EDIT_MESH")
    a.add_argument("--selected", help="observed selected object types, comma separated, e.g. MESH,MESH")
    a.add_argument("--kb", help="path to the knowledge index (default: knowledge/kb.sqlite if it exists)")
    a.add_argument("--no-kb", action="store_true", help="catalog and parsers only; ignore the documentation index and tutorial index")
    ch = sub.add_parser("chat", help="OFFLINE: talk to GuideWire in the terminal; load a tutorial and ask follow-up questions (session saved with --session)")
    ch.add_argument("--session", help="JSON file that keeps the conversation between runs")
    ch.add_argument("--script", help="read the messages from a file, one per line, instead of the keyboard")
    ch.add_argument("--version", help="your Blender version, e.g. 2.80")
    ch.add_argument("--json", action="store_true", help="print each reply as JSON (what a UI would receive)")
    ch.add_argument("--no-kb", action="store_true")
    fd = sub.add_parser("find", help="rank tutorials for a learning request (index only; --verify-captions makes Data API calls, about 50 units each)")
    fd.add_argument("text")
    fd.add_argument("--version")
    fd.add_argument("--limit", type=int, default=3)
    fd.add_argument("--index", help="a tutorial index JSON (default: knowledge/tutorial_index.json)")
    fd.add_argument("--candidates", action="store_true", help="also search the UNREVIEWED candidates file")
    fd.add_argument("--verify-captions", type=int, default=0, metavar="N", help="check caption tracks of the top N results through the official API")
    pl = sub.add_parser("playlist", help="NETWORK (Data API, about 2 quota units): list the videos of a playlist so one can be chosen")
    pl.add_argument("url")
    t = sub.add_parser("transcript", help="OFFLINE: parse a user-supplied SRT/VTT or timestamped transcript into narrated steps")
    t.add_argument("file")
    t.add_argument("--duration", type=float)
    t.add_argument("--version")
    t.add_argument("-o", "--out")
    c = sub.add_parser("captions", help="OPT-IN: fetch captions for ONE public video (third-party library, undocumented endpoint), then run the offline transcript route")
    c.add_argument("video", help="YouTube URL or id")
    c.add_argument("--duration", type=float)
    c.add_argument("--version")
    c.add_argument("--purge", action="store_true", help="only delete cached captions older than 30 days, then exit")
    sub.add_parser("purge", help="OFFLINE: delete run logs, cached extractions and cached captions older than 30 days (YouTube-derived data rule)")
    m = sub.add_parser("validate", help="OFFLINE: validate and annotate a manually entered step list (JSON)")
    m.add_argument("file")
    m.add_argument("--version")
    for p in (w, v):
        p.add_argument("--app", default="blender")
        p.add_argument("-o", "--out")
        p.add_argument("--media-resolution", help="e.g. MEDIA_RESOLUTION_HIGH")
        p.add_argument("--prompt-version", default="v2", choices=["v2", "v3"],
                       help="v2 = baseline used in all recorded live runs; v3 = unevaluated candidate")
        p.add_argument("--run-log", help="append every attempt (raw response, usage, issues) to this JSONL file")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("httpx", "httpcore", "google_genai", "google.genai"):  # request logs can carry secrets
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.cmd in OFFLINE_COMMANDS:
        try:
            return _offline(args)
        except (OSError, ValueError, KeyError, LookupError, RuntimeError) as e:     # JSONDecodeError, pydantic ValidationError and ValidationFailure are ValueErrors
            if args.debug:
                raise
            print(f"error: {_one_line(e)}  (use --debug for the traceback)", file=sys.stderr)
            return 2
    from .runlog import RunLog

    hook = RunLog(args.run_log, cmd=args.cmd) if args.run_log else None
    try:
        provider = GeminiProvider(media_resolution=args.media_resolution)
        if args.cmd == "written":
            sl = extract_from_text(provider, Path(args.file).read_text(encoding="utf-8"), app=args.app,
                                   prompt_version=args.prompt_version, on_attempt=hook)
        else:
            vid = parse_video_id(args.url)
            duration = title = None
            if not args.no_metadata:
                md = fetch_metadata(vid)
                if md.privacy_status != "public":
                    print(f"Video is '{md.privacy_status}'; the URL route needs a public video.", file=sys.stderr)
                    return 2
                duration, title = md.duration_s, md.title
            sl = extract_from_video(provider, vid, app=args.app, duration_s=duration, title_hint=title,
                                    prompt_version=args.prompt_version, on_attempt=hook)
    except (ExtractionError, ValueError, RuntimeError, LookupError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    out = sl.model_dump_json(indent=2)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"wrote {len(sl.steps)} steps to {args.out}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
