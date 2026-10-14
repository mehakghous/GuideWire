"""The rigging and animation feature catalog (145 features, 22 categories) from GuideWire_Rigging_Animation_Feature_Matrix.xlsx.

Loaded from knowledge/rigging_features.json (built by scripts/import_feature_matrix.py). Ingestion uses it to say WHICH feature a tutorial step
teaches, how each app does it, what depends on what, and what counts as done. Support codes per app: N native, P partial, C custom (add-on or
script), U unsupported. Evidence: `references` says whether an official page was read; 'Recalled knowledge' rows must be checked before use.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "rigging_features.json"
APPS = ("blender", "maya", "houdini")
SUPPORT_CODES = ("N", "P", "C", "U")


@dataclass(frozen=True)
class Feature:
    id: str
    category: str                   # full name, e.g. "Skeleton, joint and bone creation"
    name: str
    outcome: str
    support: dict[str, str]         # app -> text, e.g. "N – Add > Armature"
    workflow: str
    depends_on: tuple[str, ...]
    complexity: str
    priority: str                   # P0..P3
    acceptance: str
    references: str
    group: str
    phase: int                      # 1..5
    mvp: bool

    @property
    def code(self) -> str:          # category code, e.g. "SKEL"
        return self.id.split("-")[0]

    def support_code(self, app: str) -> str:
        return self.support[app][:1]

    @property
    def verified_from_docs(self) -> bool:
        return not self.references.lower().startswith("recalled")


class Catalog:
    def __init__(self, features: list[Feature]):
        self.features = features
        self._by_id = {f.id: f for f in features}
        if len(self._by_id) != len(features):
            raise ValueError("duplicate feature ids in the catalog")
        for f in features:
            for d in f.depends_on:
                if d not in self._by_id:
                    raise ValueError(f"{f.id} depends on unknown feature {d}")
        self._check_acyclic()

    def _check_acyclic(self) -> None:
        state: dict[str, int] = {}

        def visit(fid: str) -> None:
            if state.get(fid) == 1:
                raise ValueError(f"dependency cycle through {fid}")
            if state.get(fid) == 2:
                return
            state[fid] = 1
            for d in self._by_id[fid].depends_on:
                visit(d)
            state[fid] = 2
        for f in self.features:
            visit(f.id)

    def get(self, fid: str) -> Feature:
        try:
            return self._by_id[fid.strip().upper()]
        except KeyError:
            raise KeyError(f"unknown feature id {fid!r}") from None

    def __contains__(self, fid: str) -> bool:
        return fid.strip().upper() in self._by_id

    def __len__(self) -> int:
        return len(self.features)

    def category(self, code: str) -> list[Feature]:
        return [f for f in self.features if f.code == code.upper()]

    def supported(self, app: str, codes: tuple[str, ...] = ("N", "P")) -> list[Feature]:
        """Features a tutorial for `app` can teach with the app itself (default N and P); pass ('C',) for ones that need an add-on or script."""
        return [f for f in self.features if f.support_code(app) in codes]

    def mvp(self) -> list[Feature]:
        return [f for f in self.features if f.mvp]

    def phase(self, n: int) -> list[Feature]:
        return [f for f in self.features if f.phase == n]

    def prerequisites(self, fid: str) -> list[Feature]:
        """Every feature that must come before `fid`, direct and indirect, in teaching order (prerequisites first)."""
        out: list[Feature] = []
        seen: set[str] = set()

        def walk(x: str) -> None:
            for d in self._by_id[x].depends_on:
                if d not in seen:
                    seen.add(d)
                    walk(d)
                    out.append(self._by_id[d])
        walk(self.get(fid).id)
        return out


def _feature(d: dict) -> Feature:
    m = d["phase"].split("–")[0].strip().split()[-1]
    return Feature(
        id=d["id"], category=d["category"], name=d["name"], outcome=d["outcome"],
        support={a: d[a] for a in APPS}, workflow=d["workflow"], depends_on=tuple(d["depends_on"]),
        complexity=d["complexity"], priority=d["priority"], acceptance=d["acceptance"], references=d["references"],
        group=d["group"], phase=int(m), mvp=bool(d["mvp"]),
    )


@lru_cache(maxsize=1)
def load_catalog(path: Path = CATALOG_PATH) -> Catalog:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Catalog([_feature(d) for d in data["features"]])


# Features whose result is judged by eye, so a step teaching them is craft: GuideWire shows the tutorial's reference playback and asks the
# learner to compare, and never grades it (SRS SAF-05). PROPOSED list: the matrix gives measurable tolerances for most features, so only the
# ones whose point is a creative choice are here. Review and extend it as tutorials arrive.
CRAFT_FEATURES = {
    "ANIM-04": "story poses are a performance choice",
    "CURV-04": "easing is chosen by eye",
    "FACE-05": "an expression library is judged by how the face reads",
    "CLNP-04": "arcs and spacing are judged by eye",
}


# Version differences the matrix documents, per feature and app. A step teaching one of these gets the note in `version_dependent`, so the
# learner sees it before following a tutorial recorded on another release (SRS SAF-11). Only notes the matrix states are listed here.
VERSION_NOTES: dict[str, dict[str, str]] = {
    "CTRL-06": {"blender": "Blender 4.0 replaced bone layers with bone collections"},
    "GAME-02": {"blender": "Blender 4.0 replaced bone layers with bone collections"},
    "ANIM-03": {"blender": "Blender 5.2 keys with Only Insert Available by default"},
    "ANIM-05": {"blender": "Blender 5.2 adds in-between tools"},
    "ORNT-02": {"houdini": "Houdini 22 Orient Joints v2 works on a partial skeleton"},
    "SKEL-07": {"houdini": "Houdini 22 moved templates and recipes to APEX"},
    "CTRL-08": {"houdini": "Houdini 22 builds rigs with APEX components and the Autorig Builder"},
    "IKFK-06": {"houdini": "Houdini 22 has an IK/FK Blend component (v2)"},
    "IKFK-09": {"houdini": "Houdini 22 Rest Twist counters knee flipping"},
    "CNST-01": {"houdini": "Houdini 22 has a new multi-constraint method"},
    "SKIN-09": {"houdini": "Houdini 22 Delta Mush is version 3.0"},
}
