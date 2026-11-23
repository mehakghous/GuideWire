"""What a Houdini step's words mean on screen: a node in the network editor, a parameter in the parameter pane, or a pane to act in (Tab in the network editor, F in the viewport).
The Houdini counterpart of ingestion/targets.py (Blender). Pure: reads knowledge/app_vocab/houdini.json (node types and labels, dumped from Houdini 22.0.466), never a model.

Measured on the recorded v13 Houdini runs: actions are mostly `select <node>` ("packfolder1", "APEX Configure Controls"), `set_value <parameter>` ("Control Group" = "point*"), `press_keys Tab`,
`open_menu "Tab Menu"` and `click "Scene View"`. Each becomes:
  * node   id = the node type name, label = its label, path = [the instance name] when the step names one ("packfolder1");
  * parm   prop = the label as the step writes it, panel / id = the node it belongs to (named in the step, else the node the previous action or step selected);
  * pane   id = NetworkEditor (Tab, the Tab menu, connections) or SceneViewer (a viewport key such as F, Enter, Esc; the viewport), keys = the key to press there.
Anything else is left unresolved: guidance then says the step's words and points at nothing.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from shared.step_record import Action, Step, TargetRef

VOCAB = Path(__file__).resolve().parent.parent / "knowledge" / "app_vocab" / "houdini.json"
NETWORK_WORDS = ("network view", "network editor", "tab menu", "network")
VIEWPORT_WORDS = ("scene view", "scene viewer", "viewport")
_INSTANCE = re.compile(r"\b([a-z][a-z_]*?[a-z])(\d+)\b")


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _short(type_name: str) -> str:
    """The plain name of a type: "Sop/apex::configurecontrols::2.0" -> "configurecontrols"."""
    name = type_name.split("/", 1)[-1]
    parts = [p for p in name.split("::") if p and not re.fullmatch(r"[\d.]+", p)]
    return parts[-1] if parts else name


@lru_cache(maxsize=1)
def _types() -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    """(by label key, by short name key) -> (type name, label), for SOPs."""
    try:
        d = json.loads(VOCAB.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    rows = d.get("node_types_by_category", {}).get("Sop", [])
    by_label: dict[str, tuple[str, str]] = {}
    by_name: dict[str, tuple[str, str]] = {}
    def better(new: str, old: str | None) -> bool:                    # the plain type before a dev, labs or versioned variant of the same name
        if old is None:
            return True
        rank = lambda n: (any(x in n.lower() for x in (".dev", "labs::", "dev::")), n.count("::"), len(n))      # noqa: E731
        return rank(new) < rank(old)
    for name, label in rows:
        for table, key in ((by_label, _key(label)), (by_label, _key(label).removeprefix("apex")), (by_name, _key(_short(name)))):
            if key and better(name, table.get(key, (None,))[0]):
                table[key] = (name, label)
    return by_label, by_name


def node_in(text: str) -> TargetRef | None:
    """The node a phrase names: an instance name ("packfolder1", "configurecontrols1") or a node type's label ("APEX Configure Controls", "IK AutoRig Component node")."""
    by_label, by_name = _types()
    for m in _INSTANCE.finditer(text.lower()):
        base = _key(m.group(1))
        hit = by_name.get(base) or by_name.get(base.removeprefix("apex"))
        if hit:
            return TargetRef(kind="node", label=hit[1], id=hit[0], path=[m.group(0)], confidence=1.0)
        if text.strip().lower() == m.group(0):                     # an instance name the list does not know (an older type, "animate1"): the probe reports instance names, so it can still be found
            return TargetRef(kind="node", label=m.group(0), path=[m.group(0)], confidence=0.9)
    flat = _key(text)
    labels = sorted((k for k in by_label if len(k) > 4 and k in flat), key=len, reverse=True)
    if labels:
        name, label = by_label[labels[0]]
        return TargetRef(kind="node", label=label, id=name, confidence=1.0 if _key(text).removesuffix("node") == labels[0] else 0.85)
    return None


def pane(kind: str, keys: list[str] | None = None) -> TargetRef:
    label = {"NetworkEditor": "network editor", "SceneViewer": "viewport", "Parm": "parameter pane"}[kind]
    return TargetRef(kind="pane", label=label, id=kind, keys=list(keys or []), confidence=1.0)


def resolve_action(a: Action, node: TargetRef | None = None) -> TargetRef | None:
    """The target one action means. `node` is the node the step is about (for a parameter)."""
    text = (a.ui_element or "").strip()
    low = text.lower()
    if a.verb == "press_keys" and a.keys:
        if any(k.strip().lower() == "tab" for k in a.keys):
            return pane("NetworkEditor", a.keys)
        return pane("SceneViewer", a.keys)
    if not text:
        return None
    if a.verb == "set_value" or low.startswith(("parameters >", "parameter pane >", "parameters pane >")):
        label = re.split(r"\s*>\s*", text)[-1].strip()
        return TargetRef(kind="parm", label=label, prop=label, id=node.id if node else None, panel=node.label if node else None, confidence=0.9 if node else 0.5)
    hit = node_in(text)
    if hit is not None:
        return hit
    if any(w in low for w in NETWORK_WORDS):
        return pane("NetworkEditor", ["Tab"] if "tab" in low else [])
    if any(w in low for w in VIEWPORT_WORDS):
        return pane("SceneViewer")
    return None


def resolve_step(step: Step, carried: TargetRef | None = None) -> tuple[Step, TargetRef | None]:
    """A copy of the step with targets on the actions it can resolve, and the node it leaves selected (carried to the next step for a parameter it does not name a node for).
    The node a parameter belongs to: the node the step's own words name, if exactly one; else the last node an earlier action of the step named; else the one carried in."""
    named = [n for n in (node_in(h.text) for h in step.how_to) if n is not None]
    goal = node_in(step.goal)
    if goal is not None:
        named.insert(0, goal)
    distinct = {n.id for n in named}
    node = named[0] if len(distinct) == 1 else carried
    actions = []
    for a in step.actions:
        t = resolve_action(a, node)
        if t is not None and t.kind == "node":
            node = t
        actions.append(a.model_copy(update={"target": t}) if t is not None else a)
    return step.model_copy(update={"actions": actions}), node


def resolve_steps(steps: list[Step]) -> list[Step]:
    out, carried = [], None
    for s in steps:
        r, carried = resolve_step(s, carried)
        out.append(r)
    return out
