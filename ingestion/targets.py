"""Resolve what a step's words MEAN in the application: `Action.ui_element` text -> a typed `TargetRef`, by looking the words up in the application's own interface catalog
(`knowledge/app_vocab/blender_ui.json`, dumped from Blender by `scripts/dump_ui_catalog.py`). Deterministic and offline: no model call, nothing guessed.

Why: a tutorial writes "Toolbar > Loop Cut", "Mode selector > Edit Mode", "Properties > Data > Viewport Display > In Front". None of those strings exist on screen. Guidance that matches such words against
pixels is guessing; guidance that knows the TOOL is `builtin.loop_cut` in Edit Mesh mode, the MODE is `EDIT`, the PANEL is Viewport Display on the Data tab, can ask Blender where those are (Part C).

What it does NOT do: invent. A phrase that matches nothing stays unresolved (`None`) and guidance falls back to the words. An ambiguous match keeps all candidates and a lower confidence.

The words that name a PLACE in Blender's window ("Toolbar", "Mode selector", "Properties", "Viewport Context Menu") are listed in CONTAINERS below, with the kind of target each introduces. They are Blender's own region
names, not per-tutorial rules; everything else (tool ids, operators, panels, tabs, menus, key bindings) comes from the catalog.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from shared import shortcuts
from shared.step_record import Action, Step, StepList, TargetRef

CATALOG = Path(__file__).resolve().parent.parent / "knowledge" / "app_vocab" / "blender_ui.json"
VOCAB = Path(__file__).resolve().parent.parent / "knowledge" / "app_vocab" / "blender.json"

CONTAINERS = {
    "toolbar": "tool", "tool bar": "tool", "tools": "tool", "tool shelf": "tool",
    "mode selector": "mode", "mode dropdown": "mode", "mode menu": "mode", "mode": "mode", "interaction mode": "mode",
    "properties": "property", "properties editor": "property", "properties panel": "property", "property editor": "property",
    "viewport context menu": "context_menu", "context menu": "context_menu", "right-click menu": "context_menu", "right click menu": "context_menu",
}
_SEP = re.compile(r"\s*(?:>|›|→|‣|->)\s*")


def _n(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


@dataclass
class Catalog:
    version: str | None
    tools: dict[str, list[tuple[str, str, int]]]            # tool label (lower) -> [(mode, tool id, cell index)]
    tool_ids: dict[str, list[tuple[str, int]]]              # tool id -> [(mode, cell)]
    ops_by_label: dict[str, list[str]]                      # operator label (lower) -> operator ids
    ops: dict[str, dict]                                    # operator id -> {"label", "props"}
    menus: dict[str, list[str]]                             # menu label (lower) -> menu class ids
    tabs: dict[str, str]                                    # tab label (lower) -> tab id
    panels: dict[tuple[str, str], list[str]]                # (tab context, panel label lower) -> panel ids
    modes: dict[str, str]                                   # mode label (lower) -> enum id
    mode_order: list[str] = field(default_factory=list)     # the order modes were dumped in (toolbar lookup tries the step's mode first, then these)
    names: frozenset[str] = frozenset()                     # every UI name known (flat list from blender.json), for checking menu path segments

    @classmethod
    def from_dict(cls, d: dict[str, Any], names: frozenset[str] = frozenset()) -> Catalog:
        tools: dict[str, list[tuple[str, str, int]]] = {}
        tool_ids: dict[str, list[tuple[str, int]]] = {}
        for mode, rows in d.get("tools", {}).items():
            cell = -1
            for row in rows:
                if row.get("separator"):
                    continue
                cell += 1
                for t in row.get("group", []):
                    tools.setdefault(_n(t["label"]), []).append((mode, t["id"], cell))
                    tool_ids.setdefault(t["id"], []).append((mode, cell))
        ops = d.get("operators", {})
        by_label: dict[str, list[str]] = {}
        for oid, o in ops.items():
            by_label.setdefault(_n(o["label"]), []).append(oid)
        menus: dict[str, list[str]] = {}
        for m in d.get("menus", []):
            menus.setdefault(_n(m["label"]), []).append(m["id"])
        panels: dict[tuple[str, str], list[str]] = {}
        for p in d.get("panels", []):
            if p.get("space") == "PROPERTIES" and p.get("context"):
                panels.setdefault((p["context"].lower(), _n(p["label"])), []).append(p["id"])
        modes: dict[str, str] = {}
        for k, v in d.get("modes", {}).items():
            modes.setdefault(_n(v), k)                           # "Edit Mode" is EDIT and EDIT_GPENCIL: the first (general) one
        return cls(d.get("version"), tools, tool_ids, by_label, ops, menus, {_n(v): k for k, v in d.get("tabs", {}).items()}, panels, modes, list(d.get("tools", {})), names)


@lru_cache(maxsize=1)
def load_catalog() -> Catalog | None:
    """The Blender catalog, or None when the file is missing (resolution is then skipped and steps keep their words)."""
    import json
    try:
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        names = frozenset(_n(x) for x in json.loads(VOCAB.read_text(encoding="utf-8")).get("ui_names", []))
    except (OSError, ValueError):
        names = frozenset()
    return Catalog.from_dict(data, names)


def _module_for_mode(mode: str | None) -> str | None:
    """The operator module an editing mode uses: EDIT_MESH -> mesh, EDIT_ARMATURE -> armature, POSE -> pose. Blender names them that way; nothing to maintain."""
    if not mode:
        return None
    return mode[len("EDIT_"):].lower() if mode.startswith("EDIT_") else mode.lower()


def _pick_operator(cat: Catalog, label: str, mode: str | None) -> tuple[str | None, list[str], float]:
    """(operator id, candidates, confidence) for an operator label. Several operators share a label ("Subdivide" is mesh, armature, curve, ...): the one in the step's mode wins."""
    ids = cat.ops_by_label.get(_n(label), [])
    if not ids:
        return None, [], 0.0
    if len(ids) == 1:
        return ids[0], [], 1.0
    module = _module_for_mode(mode)
    mine = [i for i in ids if module and i.split(".")[0] == module]
    if len(mine) == 1:
        return mine[0], [i for i in ids if i != mine[0]], 1.0
    return (mine[0] if mine else None), [i for i in ids if i not in mine[:1]], 0.5 if mine else 0.3


def _prop(cat: Catalog, op: str, label: str, depth: int = 0) -> tuple[str, str] | None:
    """(property id, the operator that owns it) for a property label of an operator. A macro operator (Loop Cut and Slide = Loop Cut + Edge Slide) lists its parts as properties named
    `MESH_OT_loopcut`: the property is searched in those operators too ("Number of Cuts" belongs to mesh.loopcut)."""
    want = _n(label)
    props = cat.ops.get(op, {}).get("props", [])
    for p in props:
        if _n(p["label"]) == want or p["id"].lower() == want.replace(" ", "_"):
            return p["id"], op
    if depth < 2:
        for p in props:
            m = re.fullmatch(r"([A-Z0-9]+)_OT_(\w+)", p["id"])
            if m and f"{m.group(1).lower()}.{m.group(2)}" in cat.ops:
                hit = _prop(cat, f"{m.group(1).lower()}.{m.group(2)}", label, depth + 1)
                if hit:
                    return hit
    return None


def _choice(cat: Catalog, op: str, label: str) -> tuple[str, str] | None:
    """(property id, choice id) when `label` is one of the choices of an enum property of the operator ("Set Parent To" -> type -> "With Automatic Weights")."""
    want = _n(label)
    for p in cat.ops.get(op, {}).get("props", []):
        for cid, clabel in (p.get("choices") or {}).items():
            if _n(clabel) == want:
                return p["id"], cid
    return None


def _tool(cat: Catalog, label: str, mode: str | None) -> TargetRef | None:
    hits = cat.tools.get(_n(label))
    if not hits:                                                 # the tutorial wrote an id-like name ("loop_cut")
        slug = _n(label).replace(" ", "_")
        hits = [(m, i, c) for i, mc in cat.tool_ids.items() if i.split(".")[-1] == slug for (m, c) in mc]
    if not hits:
        return None
    in_mode = [h for h in hits if h[0] == mode]
    if in_mode:
        ids = sorted({h[1] for h in in_mode})
        return TargetRef(kind="tool", label=label, id=ids[0], mode=mode, candidates=ids[1:], confidence=1.0 if len(ids) == 1 else 0.6, catalog_version=cat.version)
    first_mode = next((m for m in cat.mode_order if any(h[0] == m for h in hits)), hits[0][0])
    ids = sorted({h[1] for h in hits if h[0] == first_mode})
    return TargetRef(kind="tool", label=label, id=ids[0], mode=first_mode, candidates=ids[1:] + sorted({h[1] for h in hits} - set(ids)), confidence=0.6, catalog_version=cat.version)


def resolve_action(action: Action, mode_hint: str | None = None, cat: Catalog | None = None, context_operator: str | None = None) -> TargetRef | None:
    """The target an action means, or None. `mode_hint` is the interaction mode the step starts in (EDIT_MESH ...): the toolbar and the operators differ per mode. `context_operator` is the operator the
    step's earlier key press or menu item started: its pop-up menu has a title Blender does not list ("Set Parent To" is the popup of Make Parent, Ctrl+P), so a choice in it is looked up in that operator."""
    cat = cat or load_catalog()
    if cat is None:
        return None
    if action.verb == "press_keys" and action.keys:
        plain = [k for k in action.keys if shortcuts.normalize_key(k) not in shortcuts.MODIFIER_ORDER]
        first = [k for k in action.keys if shortcuts.normalize_key(k) in shortcuts.MODIFIER_ORDER] + plain[:1]     # a chord is modifiers + one key; more keys are a sequence ("R 9 0 Enter"): the first key starts it
        ops = shortcuts.operator_for_keys(first, mode_hint)
        conf = 1.0 if len(ops) == 1 else (0.5 if ops else 0.3)
        return TargetRef(kind="keys", label="+".join(action.keys), keys=list(action.keys), operator=ops[0] if len(ops) == 1 else None, candidates=ops if len(ops) > 1 else [],
                         confidence=min(conf, 0.7) if len(plain) > 1 else conf, catalog_version=cat.version)
    ui = (action.ui_element or "").strip()
    if not ui:
        return None
    segs = [s for s in _SEP.split(ui) if s]
    if not segs:
        return None
    if ":" in segs[0] and CONTAINERS.get(_n(segs[0].split(":", 1)[0])):          # "Properties:Object > Viewport Display > In Front": the tab after a colon
        container, _, tabname = segs[0].partition(":")
        segs = [container.strip(), tabname.strip(), *segs[1:]]
    head, leaf = _n(segs[0]), segs[-1]
    kind = CONTAINERS.get(head)
    v = cat.version

    if kind == "tool" and len(segs) >= 2:
        return _tool(cat, leaf, mode_hint)
    if kind == "mode" and len(segs) >= 2:
        mid = cat.modes.get(_n(leaf))
        return TargetRef(kind="mode", label=leaf, id=mid, confidence=1.0 if mid else 0.3, catalog_version=v) if mid else None
    if kind == "context_menu" and len(segs) >= 2:
        op, cands, conf = _pick_operator(cat, leaf, mode_hint)
        return TargetRef(kind="context_menu", label=leaf, path=segs[1:], operator=op, candidates=cands, confidence=conf if op else 0.4, catalog_version=v)
    if kind == "property" and len(segs) >= 3:
        tab = cat.tabs.get(_n(segs[1])) or cat.tabs.get(_n(segs[1]).removeprefix("object ").strip())
        panel = segs[2] if len(segs) >= 4 else None
        ids = cat.panels.get((tab.lower(), _n(panel)), []) if tab and panel else []
        checks = [tab is not None] + ([bool(ids)] if panel else [])
        return TargetRef(kind="property", label=leaf, tab=tab, panel=panel, prop=leaf, path=segs[1:], candidates=ids, confidence=round(sum(checks) / len(checks), 2) if checks else 0.0, catalog_version=v)
    if kind is not None:
        return None                                              # a container word with nothing after it: nothing to point at

    # an operator's own panel: "Loop Cut and Slide > Number of Cuts" (what the operator leaves in the redo panel after it ran)
    if len(segs) == 2 and _n(segs[0]) in cat.ops_by_label:
        op, cands, conf = _pick_operator(cat, segs[0], mode_hint)
        hit = _prop(cat, op, leaf) if op else None
        if hit:
            return TargetRef(kind="operator_panel", label=leaf, operator=op, prop=hit[0], candidates=cands, confidence=conf, catalog_version=v)
        ch = _choice(cat, op, leaf) if op else None
        if ch:                                                   # a choice in the menu an operator shows ("Set Parent To > With Automatic Weights")
            return TargetRef(kind="operator_panel", label=leaf, operator=op, prop=ch[0], id=ch[1], candidates=cands, confidence=conf, catalog_version=v)
    if len(segs) == 2 and context_operator and head not in cat.menus:
        ch = _choice(cat, context_operator, leaf)
        if ch:
            return TargetRef(kind="operator_panel", label=leaf, operator=context_operator, prop=ch[0], id=ch[1], confidence=0.9, catalog_version=v)
    # a menu path: "Add > Mesh > Cylinder", "Set Parent To > With Automatic Weights"
    if len(segs) >= 2 and head in cat.menus:
        known = [(_n(s) in cat.names) for s in segs] if cat.names else []
        conf = round(sum(known) / len(known), 2) if known else 0.7
        ids = cat.menus[head]
        return TargetRef(kind="menu", label=leaf, path=segs, id=ids[0] if len(ids) == 1 else None, candidates=ids if len(ids) > 1 else [], confidence=conf, catalog_version=v)
    # one word: a toolbar tool by its label, or a thing in the viewport that the screen never names
    if len(segs) == 1:
        if head in cat.menus:
            return TargetRef(kind="menu", label=leaf, path=segs, id=cat.menus[head][0] if len(cat.menus[head]) == 1 else None, confidence=0.7, catalog_version=v)
        if action.verb != "open_menu" and head not in cat.ops_by_label and head not in cat.tools and head not in cat.tabs:
            return TargetRef(kind="viewport", label=leaf, confidence=0.5, catalog_version=v)
    return None


@dataclass
class Report:
    """What resolving a step list achieved (printed by scripts/resolve_targets.py; also what tests assert)."""
    actions: int = 0
    with_text: int = 0
    resolved: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    low_confidence: list[str] = field(default_factory=list)


def _start_mode(step: Step, carried: str | None = None) -> str | None:
    """The mode a step starts in: its own start_state, else the mode the previous steps left the application in (a tutorial does not repeat it)."""
    return next((p.target for p in step.start_state if p.kind == "mode"), carried)


def resolve_step(step: Step, cat: Catalog | None = None, report: Report | None = None, carried_mode: str | None = None) -> Step:
    """A copy of the step with `target` set on every action that could be resolved. The step's own text and the rest of the step are untouched."""
    cat = cat or load_catalog()
    if cat is None:
        return step
    mode = _start_mode(step, carried_mode)
    expected_mode = next((p.target for p in step.expected_state if p.kind == "mode"), None)
    actions = []
    context_op = None
    for a in step.actions:
        t = resolve_action(a, mode, cat, context_op)
        if t is not None and t.kind in ("keys", "context_menu") and t.operator:
            context_op = t.operator                                  # the pop-up menu that follows belongs to this operator
        if t is not None and t.kind == "mode" and t.id and expected_mode and (expected_mode == t.id or expected_mode.startswith(t.id + "_")):
            t = t.model_copy(update={"mode": expected_mode})        # the mode selector says "Edit Mode"; the step's own check says which one (EDIT_ARMATURE)
        if report is not None:
            report.actions += 1
            if a.ui_element or a.keys:
                report.with_text += 1
                if t is None:
                    report.unresolved.append(f"{step.id}: {a.verb} {a.ui_element or '+'.join(a.keys)}")
                else:
                    report.resolved += 1
                    report.by_kind[t.kind] = report.by_kind.get(t.kind, 0) + 1
                    if t.confidence < 0.8:
                        report.low_confidence.append(f"{step.id}: {a.ui_element or '+'.join(a.keys)} -> {t.kind} {t.id or t.operator or ''} ({t.confidence})")
        actions.append(a.model_copy(update={"target": t}) if t is not None else a)
    return step.model_copy(update={"actions": actions})


def resolve_steps(steps: list[Step], cat: Catalog | None = None, report: Report | None = None) -> list[Step]:
    """Resolve a tutorial's steps in order, carrying the interaction mode from one step to the next (a tutorial does not repeat it)."""
    out: list[Step] = []
    mode: str | None = None
    for st in steps:
        out.append(resolve_step(st, cat, report, mode))
        mode = next((p.target for p in st.expected_state if p.kind == "mode"), _start_mode(st, mode))      # what the next step starts in
    return out


def resolve_steplist(sl: StepList, cat: Catalog | None = None) -> tuple[StepList, Report]:
    """The step list with targets resolved (only for Blender: the catalog is Blender's), and the report."""
    report = Report()
    if sl.app != "blender":
        return sl, report
    return sl.model_copy(update={"steps": resolve_steps(sl.steps, cat, report)}), report
