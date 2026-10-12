"""Candidate procedures extracted DETERMINISTICALLY from a manual page's Reference block, with validation, conflict detection and
the audit that cross-checks the hand-written catalog against the manual.

Trust ladder for a procedure (see shared/answer.py): reviewed > catalog > doc_extracted > doc_passage > index_pointer.
A candidate here is `doc_extracted`: the mode, menu path and shortcut are exactly what the manual's Reference block states, converted
to the shared step schema. It is NOT reviewed and says nothing about selection prerequisites or option values (those live in prose
that is offered only as an excerpt). Nothing is promoted into the trusted workflow library without a named reviewer
(`promote`), and a promoted procedure records the sha256 of the source it was read from so it can be detected as stale.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from shared.step_record import Action, Step, StatePredicate as P

from ingestion.catalog import BY_ID, Prereq, normalise_shortcut, tokens
from ingestion.profiles import BLENDER, AppProfile, norm

from .index import Hit, KnowledgeBase

_KEYNAMES = {"period": ".", "comma": ",", "slash": "/", "minus": "-", "plus": "+", "return": "enter", "esc": "esc", "space": "space",
             "backspace": "backspace", "delete": "delete", "del": "delete", "tab": "tab", "ctrl": "ctrl", "shift": "shift", "alt": "alt"}
_MOUSE = re.compile(r"\b(lmb|rmb|mmb|wheel|mouse|drag|click)\b", re.I)


def normalise_kbd(raw: str) -> tuple[str | None, str]:
    """('ctrl+shift+b', 'keyboard') | (None, 'mouse'|'unparsed'). 'Shift-Ctrl-B' -> 'ctrl+shift+b'."""
    if _MOUSE.search(raw):
        return None, "mouse"
    parts = [p for p in re.split(r"[-+]", raw.strip()) if p]
    if not parts:
        return None, "unparsed"
    out = []
    for p in parts:
        low = p.lower()
        out.append(_KEYNAMES.get(low, low))
    return normalise_shortcut("+".join(out)), "keyboard"


@dataclass
class Variant:
    menu: str | None
    shortcut_raw: str | None
    shortcut: str | None
    label: str | None


@dataclass
class Candidate:
    path: str
    branch: str
    title: str
    url: str
    operators: list[str]
    modes_raw: list[str]
    variants: list[Variant]
    lead: str
    sha256: str | None = None
    notes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)     # any problem => needs_review

    @property
    def status(self) -> str:
        return "needs_review" if self.problems else "auto"


def candidate_from_hit(hit: Hit, sha256: str | None = None) -> Candidate | None:
    ref = hit.reference
    if not ref or not (ref.get("menus") or ref.get("shortcuts")):
        return None
    menus = ref.get("menus", [])
    sc = [(k, lab) for k, lab in ref.get("shortcuts", [])]
    variants: list[Variant] = []
    used: set = set()
    unlabeled = [x for x in sc if not x[1]]
    for m in menus:
        last = norm(m.split(">")[-1])
        pick = next((x for x in sc if x[1] and norm(x[1]) == last), None)
        if pick is None and len(menus) == 1 and sc:
            pick = unlabeled[0] if unlabeled else sc[0]
        if pick:
            used.add(pick)
        variants.append(Variant(m, pick[0] if pick else None, normalise_kbd(pick[0])[0] if pick else None, pick[1] if pick else None))
    for x in sc:
        if x not in used:
            variants.append(Variant(None, x[0], normalise_kbd(x[0])[0], x[1]))
    cand = Candidate(hit.path, hit.branch, hit.title, hit.url, hit.operators, ref.get("modes", []), variants, hit.lead, sha256)
    for v in variants:
        if v.shortcut_raw and v.shortcut is None:
            cand.notes.append(f"shortcut '{v.shortcut_raw}' is a mouse action or could not be parsed as a keyboard shortcut")
    if not any(v.menu for v in variants) and not any(v.shortcut for v in variants):
        cand.problems.append("the Reference block names neither a menu path nor a keyboard shortcut")
    return cand


def mode_predicate(c: Candidate) -> tuple[P | None, str | None]:
    """The vocabulary mode this page implies, only when it is unambiguous. Edit Mode is EDIT_MESH only for mesh pages."""
    raw = " ".join(c.modes_raw).lower()
    if "edit" in raw and "object" in raw:
        return None, "the manual lists both Object Mode and Edit Mode"
    if "object mode" in raw:
        return P(kind="mode", target="OBJECT"), None
    if "edit mode" in raw and c.path.startswith("modeling/meshes"):
        return P(kind="mode", target="EDIT_MESH"), None
    if raw.strip():
        return None, f"mode '{' / '.join(c.modes_raw)}' has no equivalent in this app's state vocabulary"
    return None, None


def select_variants(c: Candidate, question: str) -> list[Variant]:
    """Variants whose menu/label words appear in the question (e.g. 'bevel an EDGE' selects 'Edge > Bevel Edges'); all if none or all do."""
    q = tokens(question)
    scored = []
    for v in c.variants:
        words = tokens(" ".join(x for x in (v.menu or "", v.label or "") if x).replace(">", " "))
        generic = {"bevel", "extrude", "merge", "delete", "duplicate", "add", "mesh", "object", "edge", "edges", "vertex", "vertices", "face", "faces"}
        n = len((words & q) & {"vertex", "vertices", "edge", "edges", "face", "faces", "vertice", "vertic"})
        scored.append((n, v))
    best = max((n for n, _ in scored), default=0)
    if best == 0:
        return c.variants
    return [v for n, v in scored if n == best]


def extra_profile(base: AppProfile, names: list[str]) -> AppProfile:
    """The base vocabulary plus the menu names the manual itself states (they are authoritative for UI labels)."""
    return AppProfile(name=base.name, modes=base.modes, tools=base.tools, workspaces=base.workspaces, selection_types=base.selection_types,
                      ui_names=base.ui_names | frozenset(norm(seg) for n in names for seg in n.split(">") if seg.strip()), panels=base.panels,
                      mode_aliases=base.mode_aliases)


def candidate_steps(c: Candidate, question: str = "", observed: dict | None = None) -> tuple[list[Step], list[str], list[str], list[str]]:
    """(steps, assumptions, questions, notes). Steps are doc_reference / catalog_context only; expected state is left empty because the
    Reference block states how to start the tool, not an observable result."""
    from ingestion.knowledge import check_prereq, make_step

    vs = select_variants(c, question)
    notes = list(c.notes)
    pred, why = mode_predicate(c)
    if why:
        notes.append(why)
    steps: list[Step] = []
    assumptions: list[str] = []
    questions: list[str] = []
    if len({v.menu for v in vs}) > 1:
        questions.append("The manual lists several variants: " + "; ".join(f"{v.menu} ({v.shortcut_raw})" if v.shortcut_raw else str(v.menu) for v in vs)
                         + ". Which one do you mean?")
    first = vs[0]
    if pred is not None:
        pre = Prereq(f"Be in {' / '.join(c.modes_raw)}.", True, pred, None, "mode.enter_edit" if pred.target == "EDIT_MESH" else "mode.enter_object")
        st = check_prereq(pre, observed)
        if st == "unmet":
            op = BY_ID[pre.established_by]
            s0 = make_step(1, op.clause, op, "catalog_context", goal=f"First: {op.clause.goal[0].lower()}{op.clause.goal[1:]} (the manual says this tool works in {c.modes_raw[0]})")
            steps.append(s0)
        elif st == "unknown":
            assumptions.append(f"Assumes you are in {' / '.join(c.modes_raw)}, which the manual says this tool needs (your current mode is not known).")
    elif c.modes_raw:
        assumptions.append(f"The manual says this works in: {' / '.join(c.modes_raw)} (not checkable against observed state).")
    acts: list[Action] = []
    if first.menu:
        acts.append(Action(verb="open_menu", ui_element=first.menu))
    if first.shortcut:
        acts.append(Action(verb="press_keys", keys=[k.capitalize() if len(k) > 1 else k.upper() for k in first.shortcut.split("+")]))
    bits = ([f"choose {first.menu}"] if first.menu else []) + ([f"shortcut {first.shortcut_raw}"] if first.shortcut_raw else [])
    goal = f"{c.title}: " + (bits[0] if len(bits) == 1 and first.menu else " ".join(f"({b})" if b.startswith("shortcut") else b for b in bits)
                             if bits else "see the manual page")
    s = Step(id="s00", order=1, goal=goal.strip(), actions=acts, start_state=[pred] if pred else [], expected_state=[],
             confidence=0.6, support="unknown", provenance="doc_reference",
             source_refs=[f"doc:{c.path}@{c.branch}", *( [f"sha256:{c.sha256[:12]}"] if c.sha256 else [])],
             evidence=[f"Reference block of {c.path}"], assumptions=[
                 "Selection and option values are described in the manual's prose and are not extracted automatically.",
                 "Extracted from the manual's Reference block; not reviewed."])
    steps.append(s)
    return steps, assumptions, questions, notes


# ------------------------------------------------------------------ conflicts and audit
def _segments(path: str) -> list[set[str]]:
    return [{norm(alt) for alt in seg.split("/")} for seg in path.split(">")]


def menus_compatible(a: str, b: str) -> bool:
    """Same menu location: one path may be a prefix of the other ('Mesh > Separate' vs 'Mesh > Separate > Selection') and a segment may
    list alternatives ('Object/Mesh > Transform > Move')."""
    sa, sb = _segments(a), _segments(b)
    n = min(len(sa), len(sb))
    return n > 0 and all(sa[i] & sb[i] for i in range(n))


def detect_conflicts(items: list[tuple[str, set[str], set[str]]]) -> list[str]:
    """items: (source label, shortcuts, menu paths) for ONE operation from different sources. Reports disagreement; never merges."""
    msgs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            (la, sa, ma), (lb, sb, mb) = items[i], items[j]
            if sa and sb and not (sa & sb):
                msgs.append(f"{la} gives shortcut {sorted(sa)} but {lb} gives {sorted(sb)}")
            if ma and mb and not any(menus_compatible(x, y) for x in ma for y in mb):
                msgs.append(f"{la} gives menu {sorted(ma)} but {lb} gives {sorted(mb)}")
    return msgs


CATALOG_PAGES = {
    "object.join": "scene_layout/object/editing/join", "mesh.separate": "modeling/meshes/editing/mesh/separate",
    "transform.move": "scene_layout/object/editing/transform/move", "transform.rotate": "scene_layout/object/editing/transform/rotate",
    "transform.scale": "scene_layout/object/editing/transform/scale", "history.undo": "interface/undo_redo",
    "mode.enter_edit": "editors/3dview/modes", "select.elements": "modeling/meshes/selecting/introduction",
}


def audit_catalog(kb: KnowledgeBase, branch: str = "main") -> list[dict]:
    """Cross-check catalog shortcuts and menus against the manual's Reference blocks. Disagreements are findings to review, not auto-fixed."""
    out = []
    for op_id, path in CATALOG_PAGES.items():
        op = BY_ID[op_id]
        hit = kb.get_page(path, branch)
        if hit is None or not hit.reference:
            out.append({"op": op_id, "page": path, "status": "no Reference block on the page" if hit else "page not indexed"})
            continue
        doc_sc = {normalise_kbd(k)[0] for k, _ in hit.reference.get("shortcuts", []) if normalise_kbd(k)[0]}
        doc_menu = set(hit.reference.get("menus", []))
        cat_sc = {normalise_shortcut(s) for s in op.shortcuts}
        cat_menu = set(op.menu_paths)
        conflicts = detect_conflicts([("catalog", cat_sc, cat_menu), ("manual", doc_sc, doc_menu)])
        out.append({"op": op_id, "page": path, "catalog_shortcuts": sorted(cat_sc), "doc_shortcuts": sorted(doc_sc), "catalog_menus": sorted(cat_menu),
                    "doc_menus": sorted(doc_menu), "status": "agree" if not conflicts else "disagree", "conflicts": conflicts})
    return out


def validate_candidate(c: Candidate, kb: KnowledgeBase) -> Candidate:
    """Deterministic checks: shortcut collisions with other pages in the same mode. Adds problems; never edits the candidate."""
    for v in c.variants:
        if not v.shortcut:
            continue
        for other in kb.pages_with_shortcut(v.shortcut, c.branch):
            if other["path"] != c.path and set(other["modes"]) & set(c.modes_raw) and other["title"] != c.title:
                c.problems.append(f"shortcut {v.shortcut_raw} is also listed for '{other['title']}' in the same mode ({other['path']})")
    return c


def promote(c: Candidate, reviewed_by: str, version_checked: str, store, key: str):
    """Promote a candidate into the reviewed workflow store. Requires a named reviewer and the Blender version the reviewer checked;
    the source sha256 is recorded so a later change to the page makes the entry detectable as stale."""
    from ingestion.knowledge import finish
    if not reviewed_by.strip():
        raise ValueError("promotion needs a named reviewer")
    steps, *_ = candidate_steps(c)
    for s in steps:
        s.review_status = "reviewed"
    sl = finish(steps, "catalog", version=version_checked)
    for s in sl.steps:
        s.review_status = "reviewed"
    return store.save(key, sl, reviewed_by=reviewed_by, min_version=version_checked)


def is_stale(recorded_sha256: str, current_sha256: str) -> bool:
    return recorded_sha256 != current_sha256
