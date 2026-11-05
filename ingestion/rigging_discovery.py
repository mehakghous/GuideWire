"""Find tutorials for a character rigging or animation goal (Blender, Maya, Houdini).

    "I want to rig a biped character in Maya 2024"
      -> parse_goal:       app, version, and a PLAN: the catalog features the goal needs, in teaching order, from the feature catalog
      -> search_queries:   one or two YouTube search strings (search.list costs 100 quota units per call, so the count is capped)
      -> discover_rigging: search, read metadata (1 unit per 50 videos), drop what cannot be followed, rank the rest, and say for each one
                           which plan features its title/chapters mention and which they do not

Relevance is judged from METADATA ONLY (title, chapter titles, channel, duration, licence). Nothing here knows what a video really shows;
every result says so, and `covers` is "mentioned", never "taught". Search and metadata functions are injected, so tests need no network and a
live run is an explicit choice by the caller.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from shared.answer import TutorialRecommendation

from .features import APPS, load_catalog
from .terms import suggest_feature
from .tutorials import _MAXDUR

MAX_QUERIES = 2                       # 100 quota units each; the daily quota is 10,000 units
TOO_SHORT_S = 180                     # a teaser cannot teach steps, whatever the goal
_FULL_WORDS = re.compile(r"\b(?:full|complete|entire|whole|start to finish|end to end|production|course|series|from scratch to)\b", re.I)

_APP_WORDS = {"blender": re.compile(r"\bblender\b", re.I), "maya": re.compile(r"\bmaya\b", re.I),
              "houdini": re.compile(r"\b(?:houdini|kinefx|apex)\b", re.I)}
_OFFICIAL_CHANNELS = {"blender": ("blender",), "maya": ("autodesk",), "houdini": ("sidefx",)}
_VERSION = {"maya": re.compile(r"\bmaya\s*(?:version\s*)?(20\d\d)\b", re.I), "houdini": re.compile(r"\bhoudini\s*(?:version\s*)?(\d{2}(?:\.\d)?)\b", re.I),
            "blender": re.compile(r"\bblender\s*(?:version\s*)?(\d{1,2}(?:\.\d{1,2})?)\b", re.I)}
# words in the goal -> catalog categories the goal needs. Order does not matter; the plan is sorted by dependency.
_STAGES: list[tuple[re.Pattern, tuple[str, ...], str]] = [
    (re.compile(r"\b(?:rig|rigs|rigging|rigged|autorig|control rig)\b", re.I), ("SKEL", "ORNT", "IKFK", "CTRL", "CNST", "SKIN"), "rigging"),
    (re.compile(r"\b(?:skin|skinning|weights?|weight paint\w*|bind)\b", re.I), ("SKIN",), "skinning"),
    (re.compile(r"\b(?:ik|fk|inverse kinematics|pole vector|reverse foot)\b", re.I), ("IKFK",), "IK/FK"),
    (re.compile(r"\b(?:skeleton|joints?|bones?|armature)\b", re.I), ("SKEL", "ORNT"), "skeleton"),
    (re.compile(r"\b(?:face|facial|lip.?sync|blend ?shapes?|shape keys?|morph)\b", re.I), ("FACE", "BSHP"), "facial"),
    (re.compile(r"\b(?:animat\w*|keyframes?|keying|graph editor|dope sheet|timing)\b", re.I), ("ANIM", "CURV"), "animation"),
    (re.compile(r"\b(?:walk cycle|run cycle|locomotion|walking)\b", re.I), ("LOCO", "ANIM", "CURV"), "locomotion"),
    (re.compile(r"\b(?:retarget\w*|mocap|motion capture)\b", re.I), ("LAYR", "MOCP"), "retargeting / mocap"),
    (re.compile(r"\b(?:export\w*|unreal|unity|game engine|fbx|gltf)\b", re.I), ("EXPT", "GAME"), "export"),
    (re.compile(r"\b(?:constraints?|parent constraint|aim constraint)\b", re.I), ("CNST",), "constraints"),
]
_AUTO_RIG = re.compile(r"\b(?:quick rig|auto.?rig\w*|one.?click|auto skinning|advance[d]? skeleton|rigify|mixamo)\b", re.I)
_SERIES = re.compile(r"\b(?:part|pt|episode|ep|lesson|day)\s*\.?\s*(\d+)\b", re.I)
_REQUEST_WORDS = frozenset("""and or also plus i want to need how do can you please show me teach learn tutorial tutorials video videos find looking for a an the my
of in on with using use make making create creating build building set up setup from scratch beginner beginners step by""".split())


# wording that shows a title or chapter is about an AREA (category) at all. Looser than a feature match on purpose: "IK Legs" names no catalog feature but is about IK.
_AREA_WORDS = {
    "SKEL": re.compile(r"\b(?:skeleton|joints?|bones?|armature|hand rig|finger)\b", re.I),
    "ORNT": re.compile(r"\b(?:orient\w*|local axes|joint axis|rest pose|t.?pose|zero pose)\b", re.I),
    "IKFK": re.compile(r"\b(?:ik|fk|ik.?fk|inverse kinematics|forward kinematics|pole vector|reverse foot|foot roll|spline ik)\b", re.I),
    "CTRL": re.compile(r"\b(?:controls?|controllers?|ctrls?|picker)\b", re.I),
    "CNST": re.compile(r"\b(?:constraints?|space switch\w*|parent constraint|aim)\b", re.I),
    "SKIN": re.compile(r"\b(?:skin\w*|weights?|weight paint\w*|bind\w*|delta mush|deform\w*)\b", re.I),
    "FACE": re.compile(r"\b(?:face|facial|lip.?sync|eyes?|jaw|expressions?)\b", re.I),
    "BSHP": re.compile(r"\b(?:blend ?shapes?|shape keys?|morph\w*|correctives?)\b", re.I),
    "ANIM": re.compile(r"\b(?:animat\w*|keyframes?|keying|poses?|blocking)\b", re.I),
    "CURV": re.compile(r"\b(?:graph editor|dope sheet|curves?|tangents?|interpolation|timeline)\b", re.I),
    "LOCO": re.compile(r"\b(?:walk|run|cycle|locomotion)\b", re.I),
    "LAYR": re.compile(r"\b(?:layers?|retarget\w*|nla|clips?|humanik|bake)\b", re.I),
    "MOCP": re.compile(r"\b(?:mocap|motion capture|bvh)\b", re.I),
    "EXPT": re.compile(r"\b(?:export\w*|fbx|gltf|usd|alembic)\b", re.I),
    "GAME": re.compile(r"\b(?:game|unreal|unity|engine)\b", re.I),
}


@dataclass
class RiggingGoal:
    app: str | None                       # None = the request does not say which application
    version: str | None
    topic: list[str]                      # request words that are not filler or the application name
    stages: list[str]                     # human names of the stages found ("rigging", "skinning" ...)
    plan: list[str]                       # feature ids the goal asks for, in teaching order
    areas: list[str] = field(default_factory=list)            # category codes of the plan (SKEL, IKFK ...): what a tutorial must touch to be relevant
    prerequisites: list[str] = field(default_factory=list)    # features the plan assumes first (scene set-up, rest pose ...), reported, not searched for
    needs_app: bool = False
    notes: list[str] = field(default_factory=list)
    max_duration_s: int | None = None     # a limit the user stated ("under 20 minutes"); the only length that excludes a video
    full_scope: bool = False              # the user asked for the whole thing ("complete", "start to finish"): long videos are expected


@dataclass
class RiggingDiscovery:
    goal: RiggingGoal
    recommendations: list[TutorialRecommendation]
    queries: list[str] = field(default_factory=list)
    quota_units: int = 0                  # what the search and metadata calls cost
    excluded: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def parse_goal(query: str, app: str | None = None, version: str | None = None) -> RiggingGoal:
    q = query or ""
    named = [a for a in APPS if _APP_WORDS[a].search(q)]
    if app is None and len(named) == 1:
        app = named[0]
    notes = []
    if app is None and len(named) > 1:
        notes.append(f"The request names more than one application ({', '.join(named)}); say which one you use.")
    if version is None and app:
        m = _VERSION[app].search(q)
        version = m.group(1) if m else None
    cat = load_catalog()
    stages, codes = [], []
    for pat, cs, name in _STAGES:
        if pat.search(q):
            stages.append(name)
            codes += [c for c in cs if c not in codes]
    plan_ids = {f.id for f in cat.features if f.code in codes and (app is None or f.support_code(app) in ("N", "P")) and f.priority in ("P0", "P1", "P2")}
    for clause in re.split(r"[,;]| and |\.", q):                       # a feature named outright ("create an IK handle") joins the plan
        fid = suggest_feature(clause, app or "maya") if clause.strip() else None
        if fid:
            plan_ids.add(fid)
    plan = [f.id for f in cat.features if f.id in plan_ids]
    plan.sort(key=lambda i: (cat.get(i).phase, len(cat.prerequisites(i))))
    areas = list(dict.fromkeys(i.split("-")[0] for i in plan))
    needs = {p.id for i in plan for p in cat.prerequisites(i) if app is None or p.support_code(app) in ("N", "P")} - set(plan)
    prereqs = [f.id for f in cat.features if f.id in needs]
    topic = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if w not in _REQUEST_WORDS and not any(p.fullmatch(w) for p in _APP_WORDS.values()) and not w.isdigit()]
    md = _MAXDUR.search(q)
    maxd = int(float(md.group(1)) * (3600 if md.group(2).lower().startswith("h") else 60)) if md else None
    return RiggingGoal(app=app, version=version, topic=topic, stages=stages, plan=plan, areas=areas, prerequisites=prereqs, needs_app=app is None, notes=notes,
                       max_duration_s=maxd, full_scope=bool(_FULL_WORDS.search(q)))


def expected_length(goal: RiggingGoal) -> tuple[int, int | None, str]:
    """(shortest, longest or None for no upper bound, why) in seconds: what a tutorial for THIS goal plausibly needs. It scores, it never excludes;
    only a limit the user stated excludes. A goal that spans many areas (a whole character rig) is expected to take hours."""
    if goal.max_duration_s:
        return 0, goal.max_duration_s, f"you asked for under {goal.max_duration_s // 60} minutes"
    if goal.full_scope:
        return 90 * 60, None, "you asked for the complete thing, which usually takes a long tutorial or a series"
    if len(goal.areas) >= 5:
        return 30 * 60, None, f"{len(goal.areas)} areas to cover, so a whole-character rig rather than one part"
    if len(goal.areas) >= 3:
        return 20 * 60, 3 * 3600, f"{len(goal.areas)} areas to cover"
    if len(goal.areas) == 2:
        return 8 * 60, 75 * 60, "two areas to cover"
    return 3 * 60, 40 * 60, "a single, focused topic"



def search_queries(goal: RiggingGoal, max_queries: int = MAX_QUERIES) -> list[str]:
    """At most `max_queries` search strings: the goal in the user's words plus the application and 'tutorial', then a stage-based one."""
    if goal.app is None:
        return []
    base = " ".join(goal.topic[:6]) or "character rigging"
    out = [f"{goal.app} {base} tutorial"]
    if goal.stages:
        out.append(f"{goal.app} {goal.stages[0].split(' / ')[0]} character tutorial")
    return list(dict.fromkeys(out))[:max_queries]


def title_hint(title: str, app: str) -> str | None:
    m = _VERSION[app].search(title or "")
    return m.group(1) if m else None


def covers(entry: dict, goal: RiggingGoal) -> list[str]:
    """Plan features the title or a chapter title MENTIONS (a guess from wording: not proof the video teaches it)."""
    texts = [entry.get("title") or "", *(entry.get("chapter_titles") or [])]
    found = {suggest_feature(t, goal.app) for t in texts if t.strip()}
    return [f for f in goal.plan if f in found]


def touched_areas(entry: dict, goal: RiggingGoal) -> list[str]:
    """Areas the goal needs that the title or a chapter title is about: by area wording, or by a matched catalog feature."""
    text = " ".join([entry.get("title") or "", *(entry.get("chapter_titles") or [])])
    by_feature = {f.split("-")[0] for f in covers(entry, goal)}
    return [a for a in goal.areas if a in by_feature or (a in _AREA_WORDS and _AREA_WORDS[a].search(text))]


def entry_from_metadata(m: dict, app: str) -> dict:
    ch = (m.get("channel") or "").lower()
    official = any(w in ch for w in _OFFICIAL_CHANNELS[app])
    return {**m, "source_tier": "official" if official else "community", "app_hint": title_hint(m.get("title"), app)}


def discover_rigging(query: str, *, app: str | None = None, version: str | None = None, limit: int = 3,
                     search: Callable[[str, int], list[dict]] | None = None, metadata: Callable[[list[str]], list[dict]] | None = None,
                     local: list[dict] | None = None) -> RiggingDiscovery:
    """`search(query, max_results) -> [{video_id, title, channel}]` and `metadata(ids) -> [video dicts]` are the live calls (None = no live search)."""
    goal = parse_goal(query, app, version)
    out = RiggingDiscovery(goal, [], notes=list(goal.notes))
    if goal.needs_app:
        out.notes.append("Which application do you use: Blender, Maya or Houdini? Tutorials differ completely between them.")
        return out
    if not goal.plan:
        out.notes.append("The request does not say which part of rigging or animation to learn (for example rigging, skinning, IK, a walk cycle).")
    entries = [e for e in (local or []) if e.get("app", goal.app) == goal.app]
    if search is not None and metadata is not None:
        out.queries = search_queries(goal)
        ids: dict[str, dict] = {}
        for qy in out.queries:
            for r in search(qy, 10):
                ids.setdefault(r["video_id"], r)
            out.quota_units += 100
        if ids:
            entries += [entry_from_metadata(m, goal.app) for m in metadata(list(ids))]
            out.quota_units += 1
    elif not entries:
        out.notes.append("No local tutorial covers this and live search was not requested, so there is nothing to recommend yet.")
    scored = []
    for e in entries:
        title = e.get("title") or ""
        other = [a for a in APPS if a != goal.app and _APP_WORDS[a].search(title)]
        if other and not _APP_WORDS[goal.app].search(title):
            out.excluded.append(f"{title} (about {other[0]}, not {goal.app})")
            continue
        if e.get("embeddable") is False or e.get("privacy") not in (None, "public", "unlisted"):
            out.excluded.append(f"{title} (cannot be embedded or is not public)")
            continue
        cov = covers(e, goal)
        text = " ".join([title, *(e.get("chapter_titles") or [])])
        if goal.stages and not cov and not any(p.search(text) for p, _, name in _STAGES if name in goal.stages) and not touched_areas(e, goal):
            out.excluded.append(f"{title} (nothing in its title or chapters is about {', '.join(goal.stages)})")
            continue
        hit_areas = touched_areas(e, goal)
        score = 4.0 * (len(hit_areas) / len(goal.areas) if goal.areas else 0.0)
        notes = []
        if _APP_WORDS[goal.app].search(title):
            score += 3.0
        else:
            score -= 1.0
            notes.append(f"the title does not say it is for {goal.app}")
        hint = e.get("app_hint") or title_hint(title, goal.app)
        if goal.version and hint:
            same = hint.split(".")[0] == goal.version.split(".")[0]
            score += 1.0 if same else -1.5
            if not same:
                notes.append(f"recorded for {goal.app} {hint}, you use {goal.version}: menus and names may differ")
        elif goal.version:
            notes.append(f"its {goal.app} version is not stated, so compatibility is unknown")
        dur = e.get("duration_s")
        lo, hi, why = expected_length(goal)
        if dur is not None and goal.max_duration_s and dur > goal.max_duration_s:
            out.excluded.append(f"{title} ({dur // 60} min, longer than the {goal.max_duration_s // 60} you asked for)")
            continue
        if dur is not None and dur < TOO_SHORT_S and not goal.max_duration_s:
            score -= 1.5
            notes.append("under 3 minutes: too short to teach rigging step by step")
        elif dur is not None and dur < lo / 3:
            score -= 1.0
            notes.append(f"{dur // 60} min is short for this goal ({why}): it probably covers only part of it")
        elif dur is not None and dur >= lo and (hi is None or dur <= hi):
            score += 0.5
        elif dur is not None and hi is not None and dur > hi:
            notes.append(f"{dur // 60} min is long for this goal ({why}); it may cover more than you asked")
        score += (1.0 if e.get("source_tier") == "official" else 0.0) + (0.2 if e.get("licence") == "creativeCommon" else 0.0) + (0.3 if e.get("chapters") else 0.0)
        if goal.stages and any(p.search(text) for p, _, name in _STAGES if name in goal.stages):
            score += 1.0                                       # the title names the stage you asked for, even if no specific area
        if _AUTO_RIG.search(title) and not _AUTO_RIG.search(query):
            score -= 1.0
            notes.append("uses an automatic rigging tool, so there are few manual steps to follow or extract")
        part = _SERIES.search(title)
        if part:
            notes.append(f"part {part.group(1)} of a series: the other parts cover the rest")
        if goal.areas:
            names = {a: load_catalog().category(a)[0].category.split(",")[0].lower() for a in goal.areas}
            miss = [names[a] for a in goal.areas if a not in hit_areas]
            notes.append(f"title/chapters touch {len(hit_areas)} of {len(goal.areas)} areas you need ({', '.join(names[a] for a in hit_areas) or 'none'})" + (f"; not mentioned: {', '.join(miss)}" if miss else ""))
        notes.append("Judged from metadata only: what it actually shows is unknown until its steps are extracted.")
        scored.append((-round(score, 2), title, TutorialRecommendation(
            title=title, url=e["url"], channel=e.get("channel"), source_tier=e.get("source_tier", "unknown"), duration_s=dur, blender_version_hint=hint,
            licence=e.get("licence"), captions_available=e.get("captions_flag"), chapters=e.get("chapters") or None, published=e.get("published"),
            matched_terms=cov, score=round(score, 2), note=" ".join(n[0].upper() + n[1:] + ("" if n.endswith(".") else ".") for n in notes))))
    out.recommendations = [r for _, _, r in sorted(scored, key=lambda t: t[:2])][:limit]
    if entries and not out.recommendations:
        out.notes.append("Every candidate was ruled out; see the excluded list.")
    return out


# ------------------------------------------------------------------ record and replay (so ranking can be tuned without spending quota again)
class Recording:
    """Wrap live search/metadata so what came back can be saved (runs/cache, git-ignored, purged after 30 days like all YouTube-derived data) and replayed."""

    def __init__(self, search: Callable[[str, int], list[dict]], metadata: Callable[[list[str]], list[dict]]):
        self._search, self._metadata, self.hits, self.meta = search, metadata, {}, []

    def search(self, q: str, n: int) -> list[dict]:
        self.hits[q] = self._search(q, n)
        return self.hits[q]

    def metadata(self, ids: list[str]) -> list[dict]:
        self.meta = self._metadata(ids)
        return self.meta

    def save(self, path, goal_text: str) -> None:
        import json
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"goal": goal_text, "hits": self.hits, "metadata": self.meta}, indent=1), encoding="utf-8")


def replay(path) -> tuple[Callable[[str, int], list[dict]], Callable[[list[str]], list[dict]]]:
    import json
    from pathlib import Path
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    hits = [h for hs in d["hits"].values() for h in hs]
    return (lambda q, n: hits[:n * len(d["hits"])]), (lambda ids: [m for m in d["metadata"] if m["id"] in ids])
