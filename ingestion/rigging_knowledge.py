"""Domain knowledge for character rigging and animation, loaded from knowledge/rigging_knowledge.json.

The file holds what beginners actually ask and say (phrases), the menu paths and options of the tools (ui), prerequisites, ordered outlines, plain-language checks,
common mistakes and symptom-to-fix troubleshooting, for Maya and Blender. Each statement has a trust tier and source ids:
    official  vendor documentation          community  forum / Q&A / course advice          tutorial  said or shown in a tutorial          author  unverified reading
`load()` REFUSES a file where a statement cites an unknown source, claims `official` without an official source, names a feature that is not in the catalog, or
names an unknown app, so the file cannot quietly drift from its own rules. What is not in the file (Houdini, anything not researched) simply returns nothing:
callers fall back to the generic catalog and never invent knowledge.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .features import APPS, load_catalog

PATH = Path(__file__).resolve().parents[1] / "knowledge" / "rigging_knowledge.json"
TIERS = ("official", "community", "tutorial", "author")
_WORDS = re.compile(r"[a-z0-9]+")


class KnowledgeError(ValueError):
    """The knowledge file breaks its own rules."""


@dataclass(frozen=True)
class Statement:
    text: str
    tier: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class Entry:
    id: str
    apps: tuple[str, ...]
    features: tuple[str, ...]
    phrases: tuple[str, ...]
    ui: tuple[dict, ...]
    prerequisites: tuple[str, ...]
    outline: tuple[Statement, ...]
    facts: tuple[Statement, ...]
    verify: tuple[Statement, ...]
    mistakes: tuple[Statement, ...]
    troubleshooting: tuple[dict, ...]
    conflicts: tuple[dict, ...]


class Knowledge:
    def __init__(self, data: dict):
        self.sources: dict[str, dict] = data["sources"]
        self.entries = [self._entry(e) for e in data["entries"]]
        if len({e.id for e in self.entries}) != len(self.entries):
            raise KnowledgeError("duplicate entry ids")

    # ------------------------------------------------------------------ construction and validation
    def _stmt(self, where: str, d: dict) -> Statement:
        tier, srcs = d.get("tier"), tuple(d.get("sources", ()))
        if tier not in TIERS:
            raise KnowledgeError(f"{where}: unknown tier {tier!r}")
        for s in srcs:
            if s not in self.sources:
                raise KnowledgeError(f"{where}: unknown source {s!r}")
        if tier == "official" and not any(self.sources[s]["tier"] == "official" for s in srcs):
            raise KnowledgeError(f"{where}: marked official but cites no official source")
        if tier in ("official", "community", "tutorial") and not srcs:
            raise KnowledgeError(f"{where}: tier {tier} needs at least one source")
        return Statement(d["text"], tier, srcs)

    def _entry(self, e: dict) -> Entry:
        eid = e["id"]
        cat = load_catalog()
        for a in e["apps"]:
            if a not in APPS:
                raise KnowledgeError(f"{eid}: unknown app {a!r}")
        for f in e["features"]:
            if f not in cat:
                raise KnowledgeError(f"{eid}: unknown feature {f!r}")
        for u in e.get("ui", ()):
            for key in ("source", "options_source"):
                if key in u and u[key] not in self.sources:
                    raise KnowledgeError(f"{eid}: ui cites unknown source {u[key]!r}")
            if u.get("options_tier") == "official" and self.sources[u["options_source"]]["tier"] != "official":
                raise KnowledgeError(f"{eid}: ui options marked official from a non-official source")
        ts = []
        for t in e.get("troubleshooting", ()):
            self._stmt(f"{eid} troubleshooting", {"text": t["cause"], "tier": t["tier"], "sources": t["sources"]})
            if not t.get("symptom_phrases") or not t.get("fix"):
                raise KnowledgeError(f"{eid}: troubleshooting needs symptom_phrases and fix")
            ts.append(t)
        for c in e.get("conflicts", ()):
            for s in c["sources"]:
                if s not in self.sources:
                    raise KnowledgeError(f"{eid}: conflict cites unknown source {s!r}")
        g = lambda key: tuple(self._stmt(f"{eid} {key}", x) for x in e.get(key, ()))
        return Entry(id=eid, apps=tuple(e["apps"]), features=tuple(e["features"]), phrases=tuple(e.get("phrases", ())), ui=tuple(e.get("ui", ())),
                     prerequisites=tuple(e.get("prerequisites", ())), outline=g("outline"), facts=g("facts"), verify=g("verify"), mistakes=g("mistakes"),
                     troubleshooting=tuple(ts), conflicts=tuple(e.get("conflicts", ())))

    # ------------------------------------------------------------------ queries
    def for_feature(self, feature_id: str, app: str) -> list[Entry]:
        return [e for e in self.entries if feature_id in e.features and app in e.apps]

    def ui_names(self, app: str) -> set[str]:
        """Menu items and option names the official documentation (or a tutorial) gives for this app, split into the pieces a menu path is made of."""
        out: set[str] = set()
        for e in self.entries:
            if app not in e.apps:
                continue
            for u in e.ui:
                for seg in re.split(r"\s*(?:>|/|\(|\))\s*", u["path"]):
                    seg = re.sub(r"\b(?:options box|older help|channel box|shift-i|ctrl-p)\b|'[^']*'", "", seg, flags=re.I).strip(" ,.-")
                    if 2 < len(seg) < 40:
                        out.add(seg)
                out.update(u.get("options", ()))
        return out

    def phrases(self, app: str) -> list[tuple[str, Entry]]:
        return [(p, e) for e in self.entries if app in e.apps for p in e.phrases]

    def match_phrase(self, text: str, app: str, min_cover: float = 0.6) -> Entry | None:
        """The entry whose everyday phrase best matches `text` (share of the phrase's content words found in the text), or None. Needs a clear win."""
        words = _tokens(text)
        best: list[tuple[float, str]] = []
        for p, e in self.phrases(app):
            pw = _tokens(p)
            if pw:
                best.append((len(words & pw) / len(pw), e.id))
        best.sort(reverse=True)
        if not best or best[0][0] < min_cover:
            return None
        if len(best) > 1 and best[1][1] != best[0][1] and best[1][0] >= best[0][0] - 0.01 and best[1][0] >= min_cover:
            top_ids = {i for s, i in best if s >= best[0][0] - 0.01}
            if len(top_ids) > 1:
                return None
        return next(e for e in self.entries if e.id == best[0][1])

    def troubleshoot(self, text: str, app: str, min_cover: float = 0.6) -> tuple[Entry, dict] | None:
        """The (entry, troubleshooting item) whose symptom phrase best matches `text`, or None."""
        words = _tokens(text)
        best, hit = 0.0, None
        for e in self.entries:
            if app not in e.apps:
                continue
            for t in e.troubleshooting:
                for p in t["symptom_phrases"]:
                    pw = _tokens(p)
                    if pw and len(words & pw) / len(pw) > best:
                        best, hit = len(words & pw) / len(pw), (e, t)
        return hit if best >= min_cover else None

    def source_line(self, ids) -> str:
        return "; ".join(f"{self.sources[i]['title']} ({self.sources[i]['tier']}) {self.sources[i]['url']}" for i in ids)


_SAME = {"rename": "name", "renaming": "name", "renamed": "name", "bone": "joint", "bones": "joint", "controller": "control", "controllers": "control", "ctrl": "control", "feet": "foot", "legs": "leg"}
_STOP = frozenset("a an the of to and or in on for with from by at as is it this that my me i you your when what why how do does did can make makes get gets".split())




def _tokens(text: str) -> frozenset[str]:
    out = set()
    text = (text or "").lower()
    text = re.sub(r"\b(orient|point|scale|aim|parent)\s+constraints?\b", r"\1constraint", text)
    text = re.sub(r"\bconstraints?\s+(orient|point|scale|aim|parent)\b", r"\1constraint", text)            # "orient constraint" is ONE thing (not "orient" + "constraint"), in either word order
    for w in _WORDS.findall(text):
        if w not in _STOP:
            w = _SAME.get(w, w)
            out.add(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return frozenset(out)


@lru_cache(maxsize=1)
def load(path: Path = PATH) -> Knowledge:
    return Knowledge(json.loads(Path(path).read_text(encoding="utf-8")))
