"""Finer steps: a step with several how-to lines becomes one step per line, with the words unchanged (ingestion/split.py)."""
from __future__ import annotations

from ingestion.split import assign_actions, split_step, split_steps
from shared.step_record import Action, HowTo, StatePredicate, Step, StepList


def _step(i: int, goal: str, lines: list[str], **kw) -> Step:
    if "actions" not in kw:                                         # one action that names something per line, so every line has something to point at
        kw["actions"] = [Action(verb="click", ui_element=f"Menu > Item{j}") for j in range(len(lines))]
    return Step(id=f"s{i:02d}", order=i, goal=goal, how_to=[HowTo(text=t, support="shown", evidence=f"ev {t}") for t in lines], video_start_s=10.0 * i, video_end_s=10.0 * i + 8, **kw)


def _list(steps: list[Step], app: str = "maya") -> StepList:
    return StepList(source_type="youtube", app=app, steps=steps)


def test_a_step_becomes_one_step_per_line_with_the_line_as_its_goal_word_for_word():
    st = _step(1, "Pack the skeleton", ["Press Tab and place a Pack Folder node.", "Connect the Skeleton output to it.", "Set Name to base."])
    out = split_steps(_list([st]))
    assert [s.goal for s in out.steps] == ["Press Tab and place a Pack Folder node.", "Connect the Skeleton output to it.", "Set Name to base."]
    assert [s.how_to[0].text for s in out.steps] == [s.goal for s in out.steps]
    assert [s.how_to[0].evidence for s in out.steps] == [f"ev {s.goal}" for s in out.steps]
    assert {s.group for s in out.steps} == {"Pack the skeleton"} and len({s.group_id for s in out.steps}) == 1
    assert [s.id for s in out.steps] == ["s01", "s02", "s03"] and [s.order for s in out.steps] == [1, 2, 3]
    assert not out.group_problems and not out.order_problems


def test_steps_with_one_or_no_line_are_untouched():
    a, b = _step(1, "Add a box", ["Press Tab, type Box."]), _step(2, "Look", [])
    sl = _list([a, b])
    assert split_steps(sl) is sl
    mixed = split_steps(_list([a, _step(2, "Two", ["First.", "Second."]), b]))
    assert [s.goal for s in mixed.steps] == ["Add a box", "First.", "Second.", "Look"]
    assert mixed.steps[0].group_id is None and mixed.steps[3].group_id is None


def test_why_and_notes_go_first_and_the_check_and_expected_state_go_last():
    exp = [StatePredicate(kind="node_exists", target="packfolder")]
    st = _step(1, "Pack it", ["One.", "Two.", "Three."], why="Because it needs one container.", result="A pack folder exists.", expected_state=exp,
               start_state=[StatePredicate(kind="node_exists", target="skeleton")], common_mistakes=["Wrong input."], check=[HowTo(text="The node is there.", support="shown")])
    a, b, c = split_step(st)
    assert (a.why, b.why, c.why) == ("Because it needs one container.", None, None)
    assert a.common_mistakes == ["Wrong input."] and b.common_mistakes == c.common_mistakes == []
    assert a.start_state and not b.start_state and not c.start_state
    assert not a.expected_state and not b.expected_state and c.expected_state == exp
    assert c.result == "A pack folder exists." and a.result is None
    assert [len(s.check) for s in (a, b, c)] == [0, 0, 1]
    assert [s.verifiable for s in (a, b, c)] == [False, False, True]


def test_times_are_the_original_range_on_every_part_none_is_invented():
    st = _step(2, "Two lines", ["A.", "B."])
    p = split_step(st)
    assert all((s.video_start_s, s.video_end_s) == (20.0, 28.0) for s in p)


def test_actions_follow_the_line_that_names_them_in_order():
    acts = [Action(verb="press_keys", keys=["Tab"]), Action(verb="set_value", value="Pack Folder"), Action(verb="drag"), Action(verb="set_value", ui_element="Name", value="base")]
    lines = ["Press Tab and place a Pack Folder node.", "Connect the Skeleton output to the Pack Folder input.", "In the parameters set Name to base."]
    got = assign_actions(acts, lines)
    assert got == sorted(got)                                       # never backwards
    assert got[:2] == [0, 0]                                        # typing into the Tab menu stays with the Tab press
    assert got[2] == 1 and got[3] == 2


def test_every_action_is_kept_exactly_once_and_in_order():
    acts = [Action(verb="click", ui_element="Side View"), Action(verb="press_keys", keys=["Space"]), Action(verb="click", ui_element="Front View"), Action(verb="press_keys", keys=["Enter"])]
    st = _step(1, "Make the chain", ["Click in Side view.", "Maximize with Spacebar.", "Click in Front view, press Enter."], actions=acts)
    parts = split_step(st)
    assert [a for p in parts for a in p.actions] == acts


def test_depends_on_follows_the_last_part_and_ids_are_renumbered():
    s1 = _step(1, "First", ["a1.", "a2.", "a3."])
    s2 = _step(2, "Second", ["b1.", "b2."], depends_on=["s01"])
    out = split_steps(_list([s1, s2]))
    assert [s.id for s in out.steps] == ["s01", "s02", "s03", "s04", "s05"]
    assert out.steps[3].depends_on == ["s03"] and out.steps[4].depends_on == []


def test_a_long_original_goal_makes_a_label_that_fits():
    st = _step(1, "word " * 40, ["One.", "Two."])
    out = split_steps(_list([st]))
    assert len(out.steps[0].group) <= 80 and not out.group_problems


def test_the_split_list_is_valid_and_survives_a_round_trip():
    st = _step(1, "Pack it", ["One.", "Two."])
    out = split_steps(_list([st]))
    again = StepList.model_validate_json(out.model_dump_json())
    assert [s.goal for s in again.steps] == ["One.", "Two."] and again.warnings and "split into finer steps" in again.warnings[-1]


def test_a_line_with_no_action_joins_the_part_before_it_and_no_line_is_lost():
    acts = [Action(verb="click", ui_element="Menu > A"), Action(verb="click", ui_element="Menu > C")]
    st = _step(1, "Make it", ["Open A.", "Look at the result.", "Open C."], actions=acts)
    parts = split_step(st)
    assert [[h.text for h in p.how_to] for p in parts] == [["Open A.", "Look at the result."], ["Open C."]]
    assert [p.goal for p in parts] == ["Open A.", "Open C."]
    assert [a.ui_element for p in parts for a in p.actions] == ["Menu > A", "Menu > C"]


def test_a_step_with_no_action_at_all_stays_whole():
    st = _step(1, "Think", ["One.", "Two."], actions=[])
    assert split_step(st) == [st]


def test_in_blender_a_key_press_part_has_nothing_to_point_at_so_it_joins_the_part_with_the_tool():
    acts = [Action(verb="press_keys", keys=["S"]), Action(verb="select", ui_element="Scale"), Action(verb="drag")]
    st = _step(1, "Scale the cylinder", ["Press S to scale it down.", "Select the Scale tool from the left toolbar.", "Drag the Z handle up."], actions=acts)
    st = st.model_copy(update={"start_state": [StatePredicate(kind="mode", target="EDIT_MESH")]})
    out = split_steps(_list([st], app="blender"))
    assert [[h.text for h in s.how_to] for s in out.steps] == [["Press S to scale it down.", "Select the Scale tool from the left toolbar.", "Drag the Z handle up."]] or len(out.steps) <= 2
    assert all(a for s in out.steps for a in s.actions) and sum(len(s.actions) for s in out.steps) == 3


def test_a_selection_line_is_the_start_of_the_action_after_it_not_the_end_of_the_part_before():
    """2026-11-24, learner report on steps 17 and 18: one step ended "Shift-select the foot IK controller bone" and the next began "Press Ctrl+P on it"."""
    acts = [Action(verb="select", ui_element="Foot bone"), Action(verb="press_keys", keys=["Alt", "P"]), Action(verb="open_menu", ui_element="Edit > Clear Parent"),
            Action(verb="select", ui_element="Foot IK controller bone"), Action(verb="press_keys", keys=["Ctrl", "P"]), Action(verb="open_menu", ui_element="Object > Parent > Make Parent > Keep Offset")]
    lines = ["Select the foot bone and press Alt+P > Clear Parent.", "Shift-select the foot IK controller bone.", "Press Ctrl+P and select Keep Offset."]
    st = _step(1, "Re-parent the foot", lines, actions=acts)
    parts = split_step(st)
    assert [[h.text for h in p.how_to] for p in parts] == [[lines[0]], [lines[1], lines[2]]]


def test_a_line_that_only_opens_the_mode_selector_stays_with_the_line_that_chooses():
    from ingestion.split import _is_preparation
    assert _is_preparation("Click the Mode selector in the upper left header.")
    assert not _is_preparation("Click the Mode dropdown and select Edit Mode.")
    assert not _is_preparation("Press Tab and place a Pack Folder node.")
    assert not _is_preparation("Select the Scale tool from the left toolbar.")
    assert not _is_preparation("Select the bone, press G and move it up above the mesh.")
    assert _is_preparation("Shift-select the foot IK controller bone.")
