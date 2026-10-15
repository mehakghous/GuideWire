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


DISCOVERY_CACHE = Path(__file__).resolve().parents[1] / "runs" / "cache"      # raw live search results; tests point this elsewhere


def _reviewed_store(args):
    """The reviewed-workflow store, when one has been promoted into (knowledge/reviewed) and the documentation index is not switched off."""
    from .workflows import DEFAULT_STORE, ReviewedWorkflowStore
    return ReviewedWorkflowStore(DEFAULT_STORE) if DEFAULT_STORE.exists() and not getattr(args, "no_kb", False) else None


def _pairs(items: list[str] | None, sep: str, what: str) -> list[tuple[str, str]]:
    out = []
    for it in items or []:
        a, s, b = it.partition(sep)
        if not s:
            raise ValueError(f"{what}: expected N{sep}VALUE, got {it!r}")
        out.append((a.strip(), b))
    return out


def _review(args) -> int:
    """Human review of a generated step list: show it, edit it, promote it into the reviewed-workflow store (GW-012)."""
    from .workflows import (DEFAULT_STORE, ReviewedWorkflowStore, edit_steps, entries, load_steplist, op_key, promote, text_key)
    store = ReviewedWorkflowStore(args.store or DEFAULT_STORE)
    if args.rcmd == "list":
        rows = entries(store)
        for r in rows:
            print(f"{r['key']}  {r['app']}  {r['steps']} steps  by {r['reviewed_by']} on {r['reviewed_at'][:10]}  versions {r['min_version']}..{r['max_version'] or 'any'}")
        print(f"{len(rows)} reviewed workflow(s) in {store.dir}")
        return 0
    sl = load_steplist(args.file)
    if args.rcmd == "show":
        print(f"{sl.title or args.file}  app={sl.app}  steps={len(sl.steps)}")
        for s in sl.steps:
            print(f"{s.order:>3}. [{s.review_status}] {s.goal}   (confidence {s.confidence}" + (f", {s.feature_id}" if s.feature_id else "") + (", craft" if s.kind == "craft" else "") + ")")
            for f in s.flags:
                print(f"       ! {f}")
        return 0
    if args.rcmd == "edit":
        goals = {int(k): v for k, v in _pairs(args.set_goal, "=", "--set-goal")}
        moves = [(int(a), int(b)) for a, b in _pairs(args.move, ":", "--move")]
        new = edit_steps(sl, goals=goals, remove={int(x) for x in args.remove or []}, moves=moves)
        Path(args.out or args.file).write_text(new.model_dump_json(indent=2), encoding="utf-8")
        print(f"{len(new.steps)} steps written to {args.out or args.file}")
        return 0
    if args.rcmd == "promote":
        if bool(args.request) == bool(args.ops):
            raise ValueError("give exactly one of --request (the question or text users will send) or --ops (catalog operation ids)")
        key = text_key(args.request) if args.request else op_key([o.strip() for o in args.ops.split(",") if o.strip()])
        path = promote(store, key, sl, reviewed_by=args.by, min_version=args.min_version, max_version=args.max_version)
        print(f"promoted {len(sl.steps)} steps as {key}: {path}")
        return 0
    return 2


def _offline(args) -> int:
    """Commands that never touch the network or a model."""
    from .router import route

    if args.cmd == "purge":
        from .retention import purge_derived
        from .youtube.captions import ROOT
        removed = purge_derived(ROOT)
        print(f"removed {len(removed)} file(s) older than 30 days", *removed, sep="\n  ")
        return 0
    if args.cmd == "features":
        from .feature_report import feature_report
        from .workflows import load_steplist
        print(feature_report(load_steplist(args.file)).render())          # a step list, or an answer bundle holding one
        return 0
    if args.cmd == "review":
        return _review(args)
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
        from .rigging_discovery import discover_rigging, parse_goal
        if args.app in ("maya", "houdini") or parse_goal(args.text, args.app).stages:       # rigging and animation goals: any application
            search = metadata = rec = None
            if args.replay:                                         # a saved live run: ranking can be tuned with no quota
                from .rigging_discovery import replay
                search, metadata = replay(args.replay)
            elif args.live:
                from .rigging_discovery import Recording
                from .youtube import api
                rec = Recording(lambda q, n: api.search_videos(q, max_results=n), api.videos_metadata)
                search, metadata = rec.search, rec.metadata
            try:
                rd = discover_rigging(args.text, app=args.app, version=args.version, limit=args.limit, search=search, metadata=metadata)
            except Exception as e:
                if args.live and type(e).__name__ == "YouTubeApiError":
                    print(f"error: {e}", file=sys.stderr)
                    return 1
                raise
            g = rd.goal
            if rec is not None and rec.meta:
                import hashlib, time
                saved = DISCOVERY_CACHE / f"discovery_{hashlib.sha256(args.text.encode()).hexdigest()[:8]}_{int(time.time())}.json"
                rec.save(saved, args.text)
                print(f"raw search results saved to {saved} (replay with --replay, no quota)", file=sys.stderr)
            print(json.dumps({"goal": {"app": g.app, "version": g.version, "stages": g.stages, "areas": g.areas, "plan": g.plan, "prerequisites": g.prerequisites},
                              "queries": rd.queries, "quota_units_used": rd.quota_units, "results": [r.model_dump() for r in rd.recommendations],
                              "notes": rd.notes, "excluded": rd.excluded}, indent=1))
            return 0
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
        b = route(args.text.replace("\\n", "\n"), version=args.version, observed=obs, kb=kb, tutorials=tut, app=args.app, store=_reviewed_store(args))
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


OFFLINE_COMMANDS = ("review", "features", "purge", "ask", "transcript", "validate", "captions", "playlist", "find", "chat")


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
    a.add_argument("--app", default="blender", choices=["blender", "maya", "houdini"], help="the application the steps are for (Maya and Houdini: paste a multi-step rigging/animation procedure, one step per line or '\n')")
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
    fd.add_argument("--app", choices=["blender", "maya", "houdini"], help="the application (rigging/animation goals; otherwise read from the request)")
    fd.add_argument("--live", action="store_true", help="rigging goals: also search YouTube (Data API: 100 quota units per search, at most 2 searches, plus 1 for metadata)")
    fd.add_argument("--replay", metavar="FILE", help="rigging goals: rank a saved live run (runs/cache/discovery_*.json) again; no quota used")
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
    rv = sub.add_parser("review", help="OFFLINE: review a generated step list: show it, edit it, promote it to a reviewed workflow users are then served")
    rv.add_argument("--store", help="folder of reviewed workflows (default: knowledge/reviewed)")
    rs = rv.add_subparsers(dest="rcmd", required=True)
    rs.add_parser("list", help="reviewed workflows already stored")
    for name, h in (("show", "print a step list (a JSON file, e.g. from `ask ... > steps.json`) with flags"), ("edit", "change goals, remove or move steps"), ("promote", "mark every step reviewed and store it")):
        p = rs.add_parser(name, help=h)
        p.add_argument("file")
        if name == "edit":
            p.add_argument("--set-goal", action="append", metavar="N=TEXT", help="new goal for step N (repeatable)")
            p.add_argument("--remove", action="append", metavar="N", help="remove step N (repeatable)")
            p.add_argument("--move", action="append", metavar="N:M", help="move step N to position M, applied in order (repeatable)")
            p.add_argument("-o", "--out", help="write here instead of editing the file in place")
        if name == "promote":
            p.add_argument("--by", required=True, help="the person who reviewed the steps")
            p.add_argument("--request", help="the text users will send; the workflow is served when it matches")
            p.add_argument("--ops", help="catalog operation ids, comma separated (Blender catalog route)")
            p.add_argument("--min-version", default="2.80")
            p.add_argument("--max-version")
    ft = sub.add_parser("features", help="OFFLINE: which rigging/animation features a step list (JSON) teaches, and which prerequisites it assumes")
    ft.add_argument("file")
    sub.add_parser("purge", help="OFFLINE: delete run logs, cached extractions and cached captions older than 30 days (YouTube-derived data rule)")
    m = sub.add_parser("validate", help="OFFLINE: validate and annotate a manually entered step list (JSON)")
    m.add_argument("file")
    m.add_argument("--version")
    for p in (w, v):
        p.add_argument("--app", default="blender")
        p.add_argument("-o", "--out")
        p.add_argument("--media-resolution", help="e.g. MEDIA_RESOLUTION_HIGH")
        p.add_argument("--prompt-version", default="v2", choices=["v2", "v3", "v4"],
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
