"""Scene-chain check: derived node states come from the knowledge base, and a step that needs a node only a later step makes is caught. Offline."""
import json
from pathlib import Path

from ingestion.profiles import get_profile
from ingestion.rigging_knowledge import load
from ingestion.scene_chain import chain_report, derive_state
from ingestion.workflows import load_steplist

R6 = Path(__file__).parent / "fixtures" / "real_runs" / "R6_maya_part9_v6.json"   # real Gemini output, prompt v6, before derive_state


def test_every_effect_names_a_node_type_the_profile_knows():
    for e in load().entries:
        for f, eff in e.effects.items():
            for n in eff["makes"] + eff.get("needs", []):
                assert n in get_profile(e.apps[0]).nodes, (e.id, f, n)


def test_real_run_gains_verifiable_steps_and_stays_in_order():
    sl = load_steplist(R6)
    before = chain_report(sl)
    assert (before.verifiable, before.total) == (5, 15)
    assert derive_state(sl) == 2
    after = chain_report(sl)
    assert after.verifiable == 6 and not after.order_errors
    assert derive_state(sl) == 0                               # idempotent
    assert any("derived from the knowledge base" in f for st in sl.steps for f in st.flags)


def test_a_creation_step_moved_to_the_end_is_an_order_error():
    sl = load_steplist(R6)
    sl.steps = sl.steps[1:] + sl.steps[:1]                    # s01 creates the joints; every later joint step now comes first
    r = chain_report(sl)
    assert any("needs joint, but only step s01 makes it" in e for e in r.order_errors)


def test_nothing_made_anywhere_is_assumed_not_an_error():
    sl = load_steplist(R6)
    sl.steps = sl.steps[1:]                                    # no step makes the joints at all
    r = chain_report(sl)
    assert not r.order_errors and r.assumed.get("joint") == "s02"


def test_unknown_features_craft_steps_and_other_apps_are_left_alone():
    sl = load_steplist(R6)
    sl.steps[6].kind = "craft"                                 # s07 would gain parentConstraint
    sl.steps[11].feature_id = None                             # s12 would too
    assert derive_state(sl) == 0
    sl2 = load_steplist(R6)
    sl2.app = "blender"                                        # the file has no Blender effects: nothing is invented
    assert derive_state(sl2) == 0


def test_cli_chain_reports_and_writes(tmp_path, capsys):
    from ingestion import cli
    out = tmp_path / "chained.json"
    assert cli.main(["chain", str(R6), "-o", str(out)]) == 0
    text = capsys.readouterr().out
    assert "5/15 verifiable" in text and "6/15" in text
    assert json.loads(out.read_text(encoding="utf-8"))["steps"]
