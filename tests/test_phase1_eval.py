"""Phase 1 report: the structure numbers and the accuracy numbers, on hand-made step lists (no model, no network)."""
from ingestion.eval.gold import GoldSet, GoldStep
from ingestion.eval.phase1 import accuracy, coverage, load_gold, per_app, structure
from shared.step_record import HowTo, StatePredicate, Step, StepList


def _step(i, goal, start, end, *, state=True, flags=(), how=True, fid="SKEL-01"):
    return Step(id=f"s{i:02d}", order=i, goal=goal, video_start_s=start, video_end_s=end, feature_id=fid, flags=list(flags),
                expected_state=[StatePredicate(kind="node_exists", target="joint")] if state else [],
                how_to=[HowTo(text="do it", support="shown", evidence="x")] if how else [])


def _sl(steps, app="maya", dur=100.0):
    return StepList(source_type="youtube", app=app, video_id="vid", steps=steps, video_duration_s=dur)


def test_structure_rates_and_coverage():
    sl = _sl([_step(1, "create joints", 0, 20), _step(2, "create ik handle", 30, 50, state=False, flags=["a", "b"]),
              _step(3, "bind skin", 60, 90, how=False)])
    s = structure(sl)
    assert (s["steps"], s["mechanics_steps"]) == (3, 3)
    assert s["checkable_end_state"] == round(2 / 3, 3)
    assert s["with_how_to"] == round(2 / 3, 3)
    assert s["flags_per_step"] == round(2 / 3, 2)
    assert s["video_covered"] == 0.7                      # 20 + 20 + 30 of 100 s
    assert s["past_end"] == 0


def test_step_past_the_end_of_the_video_is_counted():
    assert structure(_sl([_step(1, "late step", 95, 130)]))["past_end"] == 1


def test_craft_steps_are_not_counted_as_mechanics():
    craft = _step(1, "make the arc feel natural", 0, 10, state=False)
    craft.kind = "craft"
    s = structure(_sl([craft, _step(2, "create joints", 10, 20)]))
    assert s["mechanics_steps"] == 1 and s["checkable_end_state"] == 1.0


def test_accuracy_is_none_without_a_human_gold_file(tmp_path):
    a = accuracy(_sl([_step(1, "create joints", 0, 20)]), None)
    assert a["gold"] is False and a["core_recall"] is None and a["precision"] is None
    assert load_gold(tmp_path, "vid") is None             # no <id>.gold.json: DRAFT / reference files are never picked up
    (tmp_path / "vid.DRAFT.gold.json").write_text("{}")
    assert load_gold(tmp_path, "vid") is None


def test_accuracy_against_a_hand_made_gold_set():
    gold = GoldSet(duration_s=100.0, annotator="test", app="maya", steps=[
        GoldStep(order=1, goal="create joints", t_start=2.0), GoldStep(order=2, goal="bind skin", t_start=62.0),
        GoldStep(order=3, goal="paint weights", t_start=80.0)])
    sl = _sl([_step(1, "create joints", 0, 20), _step(2, "bind skin", 60, 90), _step(3, "rename the controls", 95, 99)])
    a = accuracy(sl, gold)
    assert a["gold"] is True
    assert a["core_recall"] == round(2 / 3, 3)            # joints and skin matched, paint weights missed
    assert a["precision"] == round(2 / 3, 3)              # the rename step matches nothing
    assert a["timestamp_accuracy"] == 1.0


def test_per_application_average_ignores_missing_rates():
    rows = [{"app": "maya", "steps": 4, "gold": False, "checkable_end_state": 0.5, "with_how_to": 1.0, "with_check": 1.0, "with_time": 1.0,
             "with_feature_id": 1.0, "flags_per_step": 1.0, "video_covered": None},
            {"app": "maya", "steps": 6, "gold": False, "checkable_end_state": 0.3, "with_how_to": 1.0, "with_check": 1.0, "with_time": 1.0,
             "with_feature_id": 0.5, "flags_per_step": 2.0, "video_covered": 0.4}]
    m = per_app(rows)["maya"]
    assert (m["runs"], m["steps"]) == (2, 10)
    assert m["checkable_end_state"] == 0.4 and m["video_covered"] == 0.4


def test_one_step_can_cover_many_small_gold_actions():
    gold = GoldSet(duration_s=100.0, annotator="test", app="maya", steps=[
        GoldStep(order=1, goal="create the first joint", t_start=2.0), GoldStep(order=2, goal="create the second joint", t_start=8.0),
        GoldStep(order=3, goal="create the third joint", t_start=14.0), GoldStep(order=4, goal="bind skin", t_start=60.0),
        GoldStep(order=5, goal="paint weights", t_start=80.0, importance="optional")])
    sl = _sl([_step(1, "create joints for the leg: first, second and third joint", 0, 20), _step(2, "bind skin to the skeleton", 55, 70),
              _step(3, "rename the controls", 90, 99)])
    c = coverage(sl, gold)
    assert c["gold_core"] == 4
    assert c["text_recall_core"] == 1.0                    # three joints under one step, plus skin
    assert c["step_support"] == round(2 / 3, 3)            # the rename step has no gold action inside it


def test_time_only_recall_is_looser_than_text_recall():
    gold = GoldSet(duration_s=100.0, annotator="test", app="maya", steps=[GoldStep(order=1, goal="open the hypergraph window", t_start=10.0)])
    c = coverage(_sl([_step(1, "create joints", 0, 20)]), gold)
    assert c["time_recall_core"] == 1.0 and c["text_recall_core"] == 0.0


def test_overlay_readiness_counts_targets_and_checkable_targets():
    from shared.step_record import Action
    a = _step(1, "click the Rigging shelf tab", 0, 10, state=False)
    a.actions = [Action(verb="click", ui_element="Rigging Shelf Tab")]
    b = _step(2, "press Tab", 10, 20, state=True)
    b.actions = [Action(verb="press_keys", keys=["Tab"])]
    c = _step(3, "explain the setup", 20, 30, state=True)             # nothing to point at
    c.actions = [Action(verb="click", ui_element="  ")]
    s = structure(_sl([a, b, c]))
    assert s["with_target"] == round(2 / 3, 3)                        # a and b can be pointed at
    assert s["guidable"] == round(1 / 3, 3)                           # only b has a target AND an end state
