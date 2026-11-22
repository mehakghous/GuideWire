"""Check the parameter labels a Houdini step names against the parameters Houdini itself has on that node. No model; reads knowledge/app_vocab/houdini.json (`sop_parm_labels`, dumped from
Houdini 22.0.466 by scripts/dump_app_vocab.py; it covers 161 rigging-related node types, not every SOP).

Why: on the APEX FK tutorial nearly every v12 and v13 run wrote "Set Target Pattern to point*" for the node APEX Configure Controls. Houdini 22 has no parameter called Target Pattern on any SOP in the
list; the field the instructor fills is Control Group. The model reads small parameter-pane text poorly (no run ever read Control Group, Use Color or the 4.1 offset), so a wrong label must at least not
pass silently.

What it does: for each how-to line, find the nodes the line names (by the network editor's label, "APEX Configure Controls", or an instance name, "configurecontrols1"; the step's goal when the line
names none), find the labels the line says it sets ("Set <Label> to ...", "the <Label> field / parameter / dropdown / checkbox"), and report the labels none of those nodes has. A line about a node
the list does not cover (Attribute Wrangle, Merge) is never judged, nor is a line that names no node. A label that is the start of a real one ("Shape" for "Shape Override") is accepted: short, not
wrong. The tutorial may use another Houdini version, so the flag says which version the labels come from.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from shared.step_record import Step

VOCAB = Path(__file__).resolve().parent.parent / "knowledge" / "app_vocab" / "houdini.json"

_SET = re.compile(r"\b(?:set|change|enter|type|put)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9#/ ]{1,40}?)\s+(?:parameters?\s+|fields?\s+|menu\s+|dropdown\s+|value\s+)?(?:to|into|=)\s", re.I)
_NAMED = re.compile(r"\b([A-Za-z][A-Za-z0-9#/]*(?:\s+[A-Za-z0-9#/]+){0,3}?)\s+(?:field|parameter|dropdown|drop-down|menu|checkbox|toggle)s?\b")
_LEAD = frozenset({"in", "from", "on", "at", "into", "set", "select", "choose", "open", "enter", "type", "change", "press", "click", "the", "its", "this", "that", "a", "an", "each", "both", "all",
                   "and", "then", "with", "for", "of", "to", "find", "locate", "update", "new", "same", "corresponding"})      # not "use": Houdini labels start with it (Use Color)
_FUNCTION = frozenset({"the", "from", "in", "of", "to", "and", "for", "on", "its", "with", "at", "by", "or", "into"})
_NOT_LABELS = frozenset({"parameter", "parameters", "network", "network view", "network editor", "scene view", "viewport", "vex code", "vex", "code", "snippet", "properties", "parameter pane",
                         "parameters pane", "color picker", "component", "pattern", "target", "node", "nodes", "tab", "tab menu", "network view tab", "string", "text",
                         "mode", "create mode", "modify mode", "edit mode", "pose mode"})
# Nodes whose parameters are built from a script the learner chooses (an AutoRig component's own settings): the dumped list holds only the fixed ones, so their labels are never judged.
DYNAMIC = frozenset({"apexautorigcomponent", "apexautorigbuilder", "apexrigscriptcomponent", "apexscript"})
_OTHER_NODES = re.compile(r"\b(attribute wrangle|wrangle|object merge|copy to points|attribute create|attribute rename|python sop"
                          r"|(?:box|transform|null|switch|merge|blast|subnet)(?:\s+(?:node|sop)|\d+))\b", re.I)      # common words ("box" as a shape) count only when written as a node: "Merge node", "merge1"


@lru_cache(maxsize=1)
def _vocab() -> tuple[str, dict[str, frozenset[str]]]:
    try:
        d = json.loads(VOCAB.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", {}
    return d.get("version", ""), {_key(k): frozenset(lab.strip().lower() for lab in v if lab.strip()) for k, v in d.get("sop_parm_labels", {}).items()}


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def version() -> str:
    return _vocab()[0]


def nodes_in(text: str) -> list[str]:
    """Node types the text names, by their label ("APEX Configure Controls") or an instance name ("configurecontrols1"). Longest names first."""
    _, labels = _vocab()
    flat = _key(text)
    words = {_key(w.rstrip("0123456789")) for w in re.findall(r"[A-Za-z_]+\d+", text)}      # instance names: configurecontrols1 -> configurecontrols
    found = [k for k in labels if len(k) > 3 and (k in flat or k in words or k.removeprefix("apex") in words)]
    return sorted(set(found), key=len, reverse=True)


def labels_in(text: str) -> list[str]:
    """Parameter labels the text says it sets or names: "Set <Label> to ...", "the <Label> field". A phrase that starts with a preposition or a verb ("In the Driven", "FK from the Component"), holds
    a function word, or is a word for the interface itself ("Network View", "Parameters") is not taken for a label."""
    out: list[str] = []
    for rx in (_SET, _NAMED):
        for m in rx.finditer(text):
            words = re.sub(r"\s+", " ", m.group(1)).strip().split(" ")
            while words and words[0].lower() in _LEAD:
                words = words[1:]
            if not words:
                continue
            lab = " ".join(words)
            low = lab.lower()
            if not words[0][:1].isupper() or low in _NOT_LABELS or len(lab) < 3 or any(w.lower() in _FUNCTION for w in words):
                continue
            if re.search(r"\d$", words[-1]) and not words[-1].isdigit():                  # an instance name ("configurecontrols1"), not a label
                continue
            if lab not in out:
                out.append(lab)
    return out


def _known(label: str, allowed: frozenset[str]) -> bool:
    low = label.lower()
    if low in allowed or any(a.startswith(low + " ") for a in allowed):
        return True
    return any("#" in a and re.fullmatch(re.escape(a).replace(r"\#", r"\d+"), low) for a in allowed)      # a repeated parameter: "Use Input #" is "Use Input 2" on screen


def _names_other_node(line: str, nodes: list[str]) -> bool:
    """The line also talks about a node the parameter list does not cover: its labels could belong to that node."""
    m = _OTHER_NODES.search(line)
    return bool(m) and not any(_key(m.group(1)) in n for n in nodes)


def unknown_labels(step: Step) -> list[tuple[str, list[str]]]:
    """(label, nodes checked) for each parameter label the step names that none of the nodes it names has in Houdini's own parameter list. A label is judged against EVERY node the step names (a
    line about Pack Folder often names the skeleton connected to it), and not at all when the step also talks about a node the list does not cover, or a node whose parameters are dynamic:
    precision before reach."""
    _, vocab = _vocab()
    if not vocab:
        return []
    lines = [*(h.text for h in step.how_to), *(a.ui_element or "" for a in step.actions)]
    text = " ".join([step.goal, *lines])
    nodes = nodes_in(text)
    if not nodes or _names_other_node(text, nodes) or any(n in DYNAMIC for n in nodes):
        return []
    allowed = frozenset().union(*(vocab[n] for n in nodes))
    out: list[tuple[str, list[str]]] = []
    for line in lines:
        for lab in labels_in(line):
            if _known(lab, allowed) or any(k in _key(lab) for k in vocab) or any(lab == x for x, _ in out):
                continue
            out.append((lab, nodes))
    return out


def label_of(node_key: str) -> str:
    """The network editor's own name for a node key ("apexconfigurecontrols" -> "APEX Configure Controls")."""
    return _labels().get(node_key, node_key)


@lru_cache(maxsize=1)
def _labels() -> dict[str, str]:
    try:
        d = json.loads(VOCAB.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {_key(k): k for k in d.get("sop_parm_labels", {})}
