"""python -m verification detect | check STEPS.json [--scene FILE] [--snapshot snap.json]"""
import argparse
import json
import sys

from shared.step_record import StepList

from .checker import check_steplist, property_paths, render
from .runner import detect_apps, take_snapshot


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="verification")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("detect", help="which applications are installed here, and where")
    c = sub.add_parser("check", help="check a step list's expected states against a real scene, headlessly")
    c.add_argument("steps", help="a StepList JSON file (the application is read from it)")
    c.add_argument("--scene", help=".blend / .ma / .mb / .hip (default: the empty startup scene)")
    c.add_argument("--snapshot", help="use a saved snapshot instead of starting the application")
    a = ap.parse_args(argv)
    if a.cmd == "detect":
        for app, inst in detect_apps().items():
            print(f"{app:8} {inst.exe if inst else 'NOT FOUND'}")
        return 0
    with open(a.steps, encoding="utf-8") as f:
        sl = StepList.model_validate(json.load(f))
    if a.snapshot:
        with open(a.snapshot, encoding="utf-8") as f:
            snap = json.load(f)
    else:
        snap = take_snapshot(sl.app, a.scene, property_paths(sl))
    print(render(check_steplist(sl, snap), sl))
    return 0


if __name__ == "__main__":
    sys.exit(main())
