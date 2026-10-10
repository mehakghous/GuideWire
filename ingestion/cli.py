"""Command line entry point.

  python -m ingestion.cli written instructions.txt --app blender -o steps.json
  python -m ingestion.cli video https://www.youtube.com/watch?v=XXXXXXXXXXX -o steps.json

Needs GEMINI_API_KEY (and YOUTUBE_API_KEY for video metadata) in the environment or .env.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from .extract import ExtractionError, extract_from_text, extract_from_video
from .providers.gemini import GeminiProvider
from .youtube.metadata import fetch_metadata, parse_video_id


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="ingestion")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("written", help="convert written instructions (a text file) to steps")
    w.add_argument("file")
    v = sub.add_parser("video", help="convert a public YouTube tutorial to steps")
    v.add_argument("url")
    v.add_argument("--no-metadata", action="store_true", help="skip YouTube Data API call")
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
