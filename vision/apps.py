"""What differs between the supported applications. Everything else in `vision` is shared.

Text-based guidance (menus, panels, dialogs) needs only the window title, so it works in any
application. Blender additionally has icon-toolbar detection and area naming; for Maya and Houdini
those are not built yet (see `validated`).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppProfile:
    key: str                    # "blender" | "maya" | "houdini": the Step.app value
    title: str                  # text the main window title contains
    version: str                # the version the project is pinned to
    toolbar: bool               # icon toolbar detection (Blender only for now)
    validated: bool             # checked on real captures of this application
    probe: str                  # where the read-only probe lives


PROFILES = {
    "blender": AppProfile("blender", "Blender", "5.2", toolbar=True, validated=True,
                          probe="vision/blender_addon/guidewire_probe.py"),
    "maya": AppProfile("maya", "Maya", "2027", toolbar=False, validated=False,
                       probe="vision/probes/maya_probe.py"),
    "houdini": AppProfile("houdini", "Houdini", "22.0.466", toolbar=False, validated=False,
                          probe="vision/probes/houdini_probe.py"),
}


def profile(app: str) -> AppProfile:
    try:
        return PROFILES[app.lower()]
    except KeyError:
        raise ValueError(f"unsupported application {app!r}: use one of {sorted(PROFILES)}") from None
