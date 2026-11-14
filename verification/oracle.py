"""Oracle scorer: how close is the learner's scene to the tutorial's reference end state?

Both sides are snapshots in the shape the snapshot_<app>.py scripts write, plus optional fields that
let the three applications be compared fairly:

    {"app": "blender", "node_types": {"MESH": 2, "ARMATURE": 1}, "node_names": ["Cube", "Rig"],
     "mode": "OBJECT", "selection_types": ["MESH"],
     "up_axis": "Z", "unit_scale": 1.0,           # metres per scene unit (Maya is usually 0.01)
     "fps": 24, "frames": {"start": 1, "end": 120},
     "transforms": {"Cube": {"location": [0, 0, 2], "scale": [1, 1, 1]}}}

`normalize` puts positions in metres with Y up and time in seconds, so a Blender (Z up, metres), Maya
(Y up, centimetres) and Houdini (Y up, metres) scene of the same thing compare equal. `score` returns
a 0..1 total and the parts behind it; a part with nothing to compare is left out and the rest are
re-weighted, so a missing piece of data lowers confidence, never the score. Pure: no application
code, no I/O.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

WEIGHTS = {"node_types": 0.45, "transforms": 0.30, "frames": 0.10, "names": 0.10, "state": 0.05}
POSITION_TOL = 0.01          # metres
SCALE_TOL = 0.01
TIME_TOL = 0.05              # seconds


def _norm(s: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def to_y_up(v: list[float], up_axis: str) -> list[float]:
    """A position vector with Y up. Z-up (x, y, z) -> Y-up (x, z, -y)."""
    x, y, z = v
    return [x, z, -y] if up_axis.upper() == "Z" else [x, y, z]


def scale_to_y_up(v: list[float], up_axis: str) -> list[float]:
    """A scale vector keeps its signs when axes swap (scale has no direction)."""
    x, y, z = v
    return [x, z, y] if up_axis.upper() == "Z" else [x, y, z]


def normalize(snap: dict[str, Any]) -> dict[str, Any]:
    """Copy of a snapshot with positions in metres (Y up) and frames in seconds."""
    out = dict(snap)
    up, unit = snap.get("up_axis", "Y"), float(snap.get("unit_scale", 1.0))
    tf = {}
    for name, t in (snap.get("transforms") or {}).items():
        item = {}
        if "location" in t:
            item["location"] = [c * unit for c in to_y_up(t["location"], up)]
        if "scale" in t:
            item["scale"] = scale_to_y_up(t["scale"], up)
        tf[name] = item
    if tf:
        out["transforms"] = tf
    fr, fps = snap.get("frames"), snap.get("fps")
    if fr and fps:
        out["frames"] = {"start": (fr["start"] - 1) / fps, "end": (fr["end"] - 1) / fps}   # seconds from frame 1
    return out


def _multiset_f1(want: dict[str, int], have: dict[str, int]) -> float:
    w = {_norm(k): v for k, v in want.items()}
    h = {_norm(k): v for k, v in have.items()}
    hit = sum(min(w[k], h.get(k, 0)) for k in w)
    if hit == 0:
        return 0.0
    recall, precision = hit / sum(w.values()), hit / max(sum(h.values()), 1)
    return 2 * recall * precision / (recall + precision)


def _close(a: list[float], b: list[float], tol: float) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def _transforms(want: dict, have: dict) -> float:
    total = hit = 0
    for name, wt in want.items():
        ht = have.get(name)
        for key, tol in (("location", POSITION_TOL), ("scale", SCALE_TOL)):
            if key in wt:
                total += 1
                hit += bool(ht and key in ht and _close(wt[key], ht[key], tol))
    return hit / total if total else 0.0


@dataclass
class OracleScore:
    total: float                                       # 0..1, over the parts that could be compared
    parts: dict[str, float] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)  # parts with no reference data or no observed data


def _state_score(ref: dict, obs: dict) -> float:
    mode_ok = ref.get("mode") in (None, obs.get("mode"))
    want_sel = sorted(ref.get("selection_types", obs.get("selection_types", [])))
    sel_ok = want_sel == sorted(obs.get("selection_types", []))
    return (mode_ok + sel_ok) / 2


def score(reference: dict[str, Any], observed: dict[str, Any], weights: dict[str, float] | None = None) -> OracleScore:
    ref, obs = normalize(reference), normalize(observed)
    w = weights or WEIGHTS
    parts: dict[str, float] = {}
    skipped: list[str] = []

    def part(name: str, have_ref: bool, have_obs: bool, fn) -> None:
        if have_ref and have_obs:
            parts[name] = fn()
        else:
            skipped.append(name)

    part("node_types", bool(ref.get("node_types")), "node_types" in obs,
         lambda: _multiset_f1(ref["node_types"], obs["node_types"]))
    part("transforms", bool(ref.get("transforms")), "transforms" in obs,
         lambda: _transforms(ref["transforms"], obs["transforms"]))
    part("frames", bool(ref.get("frames")), bool(obs.get("frames")),
         lambda: float(all(abs(ref["frames"][k] - obs["frames"][k]) <= TIME_TOL for k in ("start", "end"))))
    part("names", bool(ref.get("node_names")), "node_names" in obs,
         lambda: len(set(ref["node_names"]) & set(obs["node_names"])) / len(set(ref["node_names"])))
    part("state", any(k in ref for k in ("mode", "selection_types")),
         any(k in obs for k in ("mode", "selection_types")), lambda: _state_score(ref, obs))
    weight = sum(w[k] for k in parts)
    total = sum(w[k] * v for k, v in parts.items()) / weight if weight else 0.0
    return OracleScore(round(total, 4), {k: round(v, 4) for k, v in parts.items()}, skipped)
