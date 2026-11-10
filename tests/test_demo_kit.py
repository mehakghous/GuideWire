"""The supervisor demo kit: the data, the seed script, the viewer, the preflight and the guide's file references. Offline; uses a temporary database."""
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


setup = _load("demo_setup")
show = _load("demo_show")
check = _load("demo_check")


def test_the_demo_data_is_six_real_tutorials_that_the_app_can_load_with_valid_groups():
    from app.step_loader import load_steps
    m = setup.manifest()
    assert len(m) == 6 and {x["app"] for x in m} == {"blender", "maya", "houdini"} and sum(1 for x in m if x["app"] == "blender") == 2
    for x in m:
        sl = load_steps(json.loads((setup.DATA / x["file"]).read_text(encoding="utf-8")))
        assert sl.source_type == "youtube" and sl.group_problems == [] and len(sl.steps) == x["steps"] and len(sl.groups) == x["groups"]
        assert sl.title == x["title"] and x["url"].endswith(x["video_id"]) and all(s.video_start_s is not None for s in sl.steps)


def test_seeding_makes_the_demo_account_with_nine_tutorials_and_is_repeatable(tmp_path):
    from app.accounts import Accounts
    from app.db import Database
    db = Database(tmp_path / "demo.sqlite")
    try:
        first = setup.seed(db)
        again = setup.seed(db)
        user = Accounts(db).login(setup.DEMO_EMAIL, setup.DEMO_PASSWORD)
        titles = [r["title"] for r in db.list_tutorials(user.id)]
    finally:
        db.close()
    assert first == {"user": setup.DEMO_EMAIL, "tutorials": 9, "added": 9} and again["added"] == 0 and again["tutorials"] == 9
    assert sum(t.startswith("Starter plan") for t in titles) == 3 and len(set(titles)) == 9


def test_the_viewer_shows_the_title_the_groups_the_menu_to_click_and_one_step_in_full():
    from shared.step_record import StepList
    sl = StepList.model_validate_json((setup.DATA / "blender_armature_EBgHRd5tJfE.json").read_text(encoding="utf-8"))
    text = show.show(sl)
    assert "Basic Rigging Tutorial" in text and "steps: 18" in text and "groups: 8" in text and "[click: Add > Mesh > Cylinder]" in text
    one = show.show_step(sl, "s02")
    assert "Add a cylinder mesh object" in one and "how to" in one and "expected  : node_exists MESH" in one
    assert "no step" in show.show_step(sl, "s99")


def test_the_preflight_passes_on_a_seeded_database_and_says_how_to_fix_a_missing_one(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    r = check.Report()
    check.check_database(r, db_path, fix=False)
    assert [t for t, _w, _f in r.lines] == [check.INFO] and "demo_setup.py" in r.lines[0][2]                    # the pre-made account is optional now
    r = check.Report()
    check.check_database(r, db_path, fix=True)                                                         # --fix creates it
    assert [t for t, _w, _f in r.lines] == [check.OK] and "9 tutorials" in r.lines[0][1]
    r = check.Report()
    check.check_ingestion(r)
    assert r.lines[0][0] == check.OK


def test_the_preflight_proves_the_journey_of_a_brand_new_account_off_screen():
    pytest.importorskip("PyQt6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    r = check.Report()
    check.check_app_starts(r)
    assert r.lines[0][0] == check.OK and "brand-new account" in r.lines[0][1], r.lines


def test_every_file_and_script_the_guide_mentions_exists():
    guide = (ROOT / "docs" / "demo_guide.md").read_text(encoding="utf-8")
    refs = set(re.findall(r"(?:scripts|demo)/[A-Za-z0-9_./-]+\.(?:py|txt|json)", guide))
    assert {"scripts/demo_setup.py", "scripts/demo_check.py", "scripts/demo_show.py", "demo/chat_script.txt", "demo/chat_tutorial.txt"} <= refs
    for ref in refs:
        if ref.startswith("local_data"):
            continue
        assert (ROOT / ref).exists(), ref
    assert "guidewire-demo-2026" in guide and setup.DEMO_PASSWORD == "guidewire-demo-2026" and setup.DEMO_EMAIL in guide


def test_the_chat_scripts_run_offline_and_give_the_answers_the_guide_describes(capsys):
    from ingestion.cli import main
    assert main(["chat", "--script", str(ROOT / "demo" / "chat_script.txt")]) == 0
    out = capsys.readouterr().out
    assert "Starter plan for rigging a character in Maya" in out and "Joint Capture" not in out and "Smooth Bind" in out and "pole vector" in out.lower()
    assert main(["chat", "--script", str(ROOT / "demo" / "chat_tutorial.txt")]) == 0
    out = capsys.readouterr().out
    assert "Loaded 18 steps" in out and "The source does not say why this step is needed" in out and "Marked s01 done" in out
