"""Documented option names in the knowledge base are checked against the REAL installs (knowledge/app_vocab/*.json, from scripts/dump_app_vocab.py)."""
import json
from pathlib import Path

import pytest

from ingestion.profiles import norm

DIR = Path(__file__).parent.parent / "knowledge" / "app_vocab"


def vocab(app):
    p = DIR / f"{app}.json"
    if not p.exists():
        pytest.skip(f"{p.name} not generated (python scripts/dump_app_vocab.py {app})")
    return json.loads(p.read_text(encoding="utf-8"))


def test_documented_option_names_exist_in_the_real_application():
    """Every `options` list in the knowledge base is a claim about what a learner will SEE. Unless the entry says where else the option lives
    (`options_in`: viewer state, dialog, button text), each option must be a parameter label of that node in Houdini, or a UI name in Blender."""
    import re

    from ingestion.rigging_knowledge import load
    h, b = vocab("houdini"), vocab("blender")
    node_labels = {norm(k): {norm(x) for x in v} for k, v in h["sop_parm_labels"].items()}
    blender_names = {norm(x) for x in b["ui_names"]}
    checked = {"houdini": 0, "blender": 0}
    for e in load().entries:
        for u in e.ui:
            if "options_in" in u or not u.get("options"):
                continue
            if "houdini" in e.apps:
                m = re.match(r"(.+?) \(SOP\)", u["path"])
                assert m and norm(m.group(1)) in node_labels, f"{e.id}: node {u['path']!r} was not dumped from the install"
                bad = [o for o in u["options"] if norm(o) not in node_labels[norm(m.group(1))]]
                assert not bad, f"{e.id}: {u['path']} has no parameter labelled {bad} in Houdini {h['version']}"
                checked["houdini"] += len(u["options"])
            if "blender" in e.apps:
                bad = [o for o in u["options"] if norm(o) not in blender_names]
                assert not bad, f"{e.id}: {u['path']}: {bad} is not a name in Blender {b['version']}"
                checked["blender"] += len(u["options"])
    assert checked["houdini"] >= 40 and checked["blender"] >= 25, checked


def test_maya_documented_attribute_labels_exist_in_the_install():
    """A Maya `ui` item with `options_node` lists labels of that node's attributes (and the choices of its enum attributes); each must exist in Maya 2027.
    Option-box window items (`options_in`) are not node attributes and cannot be read headlessly, so they are not checked."""
    from ingestion.rigging_knowledge import load
    m = vocab("maya")
    n = 0
    for e in load().entries:
        for u in e.ui:
            if "maya" in e.apps and "options_node" in u:
                labels = {norm(x) for x in m["attr_labels"][u["options_node"]]}
                bad = [o for o in u["options"] if norm(o) not in labels]
                assert not bad, f"{e.id}: {u['options_node']} has no attribute or choice labelled {bad} in Maya {m['version']}"
                n += len(u["options"])
    assert n >= 9
