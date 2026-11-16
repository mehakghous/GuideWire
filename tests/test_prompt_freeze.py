"""The extraction prompts must not change when the knowledge base grows: their menu and option names come from the frozen snapshot knowledge/prompt_names.json."""
import hashlib
import json

import pytest

from ingestion import extract
from ingestion.extract import build_system_prompt, frozen_menu_lines, menu_lines
from ingestion.profiles import get_profile
from ingestion.rigging_knowledge import Knowledge, load

# The text of the v10 prompts that the measured runs used (the snapshot was frozen from the knowledge base as it was on main before Part C, 45 entries).
# If this test fails, the prompt text changed. That is allowed only on purpose: refresh with scripts/freeze_prompt_names.py and say in the report that cached video runs
# are no longer reused and the measured results describe the earlier text.
PINNED_V10 = {"maya": (18937, "896c8af5d1"), "blender": (18666, "0302daf9de"), "houdini": (18990, "274df43550")}


def _fingerprint(app: str, version: str = "v10") -> tuple[int, str]:
    p = build_system_prompt(get_profile(app), version)
    return len(p), hashlib.sha256(p.encode()).hexdigest()[:10]


@pytest.mark.parametrize("app", ["maya", "blender", "houdini"])
def test_the_v10_prompt_is_the_text_the_measurements_used(app):
    assert _fingerprint(app) == PINNED_V10[app]


def test_the_snapshot_exists_and_lists_names_for_all_three_applications():
    d = json.loads(extract.PROMPT_NAMES_PATH.read_text(encoding="utf-8"))
    assert set(d["apps"]) == {"blender", "maya", "houdini"} and all(d["apps"][a] for a in d["apps"]) and d["frozen_from_sha256"] and d["frozen_on"]
    assert all(line.startswith("  - ") for lines in d["apps"].values() for line in lines)


def test_a_bigger_knowledge_base_does_not_change_the_prompt(monkeypatch):
    before = {a: _fingerprint(a) for a in ("maya", "blender", "houdini")}
    data = json.loads((extract.Path(__file__).resolve().parents[1] / "knowledge" / "rigging_knowledge.json").read_text(encoding="utf-8"))
    extra = json.loads(json.dumps(data["entries"][0]))
    extra["id"] = "maya.invented_for_this_test"
    extra["ui"][0]["path"] = "Invented > Menu Path For The Freeze Test"
    data["entries"].append(extra)
    bigger = Knowledge(data)
    assert any("Invented > Menu Path" in x for x in menu_lines("maya", bigger.entries))                    # the live knowledge base WOULD have changed the lines
    monkeypatch.setattr("ingestion.rigging_knowledge.load", lambda *a, **k: bigger)
    assert {a: _fingerprint(a) for a in ("maya", "blender", "houdini")} == before                            # but the prompt reads the snapshot


def test_without_a_snapshot_the_live_knowledge_base_is_used(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "PROMPT_NAMES_PATH", tmp_path / "missing.json")
    assert frozen_menu_lines("maya") == menu_lines("maya", load().entries) and len(frozen_menu_lines("maya")) > 24


def test_the_validator_still_learns_names_from_the_whole_knowledge_base():
    """Freezing the prompt must not freeze the vocabulary the validator accepts."""
    names = get_profile("maya").ui_names
    assert any("working units" in n for n in names) and any("bake" in n for n in names)
