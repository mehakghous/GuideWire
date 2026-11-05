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


def test_order_error_is_flagged_on_the_step_once():
    from ingestion.scene_chain import flag_order_errors
    sl = load_steplist(R6)
    sl.steps = sl.steps[1:] + sl.steps[:1]
    r = flag_order_errors(sl)
    assert r.order_errors and set(r.order_steps) <= {s.id for s in sl.steps}
    flagged = {s.id: [f for f in s.flags if f.startswith("order:")] for s in sl.steps}
    assert all(len(v) == 1 for sid, v in flagged.items() if sid in r.order_steps)
    assert not any(v for sid, v in flagged.items() if sid not in r.order_steps)
    flag_order_errors(sl)                                      # idempotent
    assert all(len([f for f in s.flags if f.startswith("order:")]) <= 1 for s in sl.steps)


def test_written_rigging_steps_get_derived_state_and_order_caveat():
    from ingestion.rigging_text import rigging_to_steplist
    ok, res = rigging_to_steplist("Create joints down the arm\nCreate an IK handle on the arm", "maya")
    assert not [c for c in res.caveats if c.startswith("order:")]
    assert any(p.kind == "node_exists" for st in ok.steps for p in st.expected_state)
    bad, res = rigging_to_steplist("Create an IK handle on the arm\nCreate joints down the arm", "maya")
    assert any(c.startswith("order:") for c in res.caveats)
    assert any(f.startswith("order:") for st in bad.steps for f in st.flags)


def test_transcript_route_reports_out_of_order_narration():
    from ingestion.rigging_transcript import ingest_rigging_transcript
    txt = "0:30 let's create an IK handle on the arm\n0:50 now create joints down the arm\n"
    r = ingest_rigging_transcript(txt, "maya", duration_s=600)
    assert r.steplist is not None
    assert any(l.startswith("order:") for l in r.limitations)
