"""Find the installed applications and run the snapshot scripts inside them. Override locations with GW_BLENDER, GW_MAYAPY, GW_HYTHON."""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent
_ENV = {"blender": "GW_BLENDER", "maya": "GW_MAYAPY", "houdini": "GW_HYTHON"}
_NAMES = {"blender": "blender", "maya": "mayapy", "houdini": "hython"}
_GLOBS = {
    "blender": ["C:/Program Files/Blender Foundation/Blender */blender.exe", "/Applications/Blender.app/Contents/MacOS/Blender", "/usr/bin/blender"],
    "maya": ["C:/Program Files/Autodesk/Maya*/bin/mayapy.exe", "/usr/autodesk/maya*/bin/mayapy", "/Applications/Autodesk/maya*/Maya.app/Contents/bin/mayapy"],
    "houdini": ["C:/Program Files/Side Effects Software/Houdini */bin/hython.exe", "/opt/hfs*/bin/hython"],
}


@dataclass
class AppInstall:
    app: str
    exe: str


def find_app(app: str) -> AppInstall | None:
    env = os.environ.get(_ENV[app])
    if env and Path(env).exists():
        return AppInstall(app, env)
    for pat in _GLOBS[app]:
        hits = sorted(glob.glob(pat))
        if hits:
            return AppInstall(app, hits[-1])                  # the newest version by name
    w = shutil.which(_NAMES[app])
    return AppInstall(app, w) if w else None


def detect_apps() -> dict[str, AppInstall | None]:
    return {a: find_app(a) for a in _ENV}


def _argv(inst: AppInstall, script: Path, args: list[str]) -> list[str]:
    if inst.app == "blender":
        return [inst.exe, "-b", "--factory-startup", "--python", str(script), "--", *args]
    return [inst.exe, str(script), *args]


def run_script(app: str, script: Path, args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    inst = find_app(app)
    if inst is None:
        raise FileNotFoundError(f"{app} is not installed (set {_ENV[app]} to its {_NAMES[app]} executable)")
    return subprocess.run(_argv(inst, script, args), capture_output=True, text=True, timeout=timeout)


def take_snapshot(app: str, scene: str | None, property_paths: list[str] | None = None, timeout: int = 300, attribute_paths: list[str] | None = None) -> dict:
    """Open `scene` (or the empty startup scene) in the application, read it, return the snapshot dict."""
    with tempfile.TemporaryDirectory() as d:
        req, out = Path(d, "request.json"), Path(d, "snapshot.json")
        req.write_text(json.dumps({"scene": scene, "properties": property_paths or [], "attributes": attribute_paths or [], "out": str(out)}), encoding="utf-8")
        p = run_script(app, HERE / f"snapshot_{app}.py", [str(req)], timeout)
        if not out.exists():
            tail = (p.stderr or p.stdout or "").strip().splitlines()[-5:]
            raise RuntimeError(f"{app} produced no snapshot (exit {p.returncode}): " + " | ".join(tail))
        return json.loads(out.read_text(encoding="utf-8"))


def run_recipes(app: str, recipes: dict[str, str], timeout: int = 600) -> dict:
    """Run each recipe (feature id -> code) in an empty scene of the real application. Returns {"version", "results": {feature: {"before", "after"} | {"error"}}}."""
    with tempfile.TemporaryDirectory() as d:
        req, out = Path(d, "request.json"), Path(d, "probe.json")
        req.write_text(json.dumps({"recipes": recipes, "out": str(out)}), encoding="utf-8")
        p = run_script(app, HERE / f"probe_{app}.py", [str(req)], timeout)
        if not out.exists():
            tail = (p.stderr or p.stdout or "").strip().splitlines()[-5:]
            raise RuntimeError(f"{app} produced no probe result (exit {p.returncode}): " + " | ".join(tail))
        return json.loads(out.read_text(encoding="utf-8"))
