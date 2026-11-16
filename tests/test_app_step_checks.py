import pytest

from app.step_checks import OBSERVABLE_KINDS, checkability
from ingestion.evaluator import evaluate_step
from shared.step_record import PredicateKind, StatePredicate, Step

# One example predicate and a state that satisfies it, for every kind.
EXAMPLES = {
    "mode": (StatePredicate(kind="mode", target="OBJECT"), {"mode": "OBJECT"}),
    "active_tool": (StatePredicate(kind="active_tool", target="builtin.move"), {"active_tool": "builtin.move"}),
    "workspace": (StatePredicate(kind="workspace", target="Modeling"), {"workspace": "Modeling"}),
    "selection_type": (StatePredicate(kind="selection_type", target="MESH"), {"selection_types": ["MESH"]}),
    "panel_open": (StatePredicate(kind="panel_open", target="Properties:Modifiers"), {"open_panels": ["Properties:Modifiers"]}),
    "node_exists": (StatePredicate(kind="node_exists", target="joint"), {"nodes": ["joint"]}),
    "property_equals": (StatePredicate(kind="property_equals", target="object.location.x", value=2.0), {"properties": {"object.location.x": 2.0}}),
    "name_exists": (StatePredicate(kind="name_exists", target="hip_jnt"), {"names": ["hip_jnt"]}),
    "attribute_exists": (StatePredicate(kind="attribute_exists", target="a.b"), {"attributes": {"a.b": True}}),
    "node_count": (StatePredicate(kind="node_count", target="joint", value=3), {"nodes": ["joint"] * 3}),
}


def step(*preds, kind="mechanics"):
    return Step(id="s1", order=1, goal="do it", expected_state=list(preds), kind=kind)


def test_every_predicate_kind_is_covered_by_the_examples():
    from typing import get_args
    assert set(get_args(PredicateKind)) == set(EXAMPLES)


@pytest.mark.parametrize("kind", sorted(EXAMPLES))
def test_the_observable_list_matches_what_the_evaluator_can_judge(kind):
    pred, state = EXAMPLES[kind]
    verdict = evaluate_step(step(pred), state)
    can_judge = verdict.status in ("met", "unmet")
    assert can_judge == (kind in OBSERVABLE_KINDS), f"{kind}: evaluator says {verdict.status}"


def test_a_step_with_nothing_to_check_is_manual():
    assert checkability(step()).level == "manual"


def test_a_craft_step_is_manual():
    assert checkability(step(EXAMPLES["mode"][0], kind="craft")).level == "manual"


def test_a_step_with_readable_state_is_checkable():
    c = checkability(step(EXAMPLES["mode"][0], EXAMPLES["selection_type"][0]))
    assert c.level == "checkable" and c.badge == "Checkable" and "once it can read" in c.text


def test_a_step_with_only_unreadable_kinds_is_manual_and_names_them():
    c = checkability(step(EXAMPLES["node_count"][0], EXAMPLES["name_exists"][0]))
    assert c.level == "manual" and "that a node has the name you gave it and how many nodes of a type exist" in c.text


def test_a_mixed_step_is_partly_checkable():
    c = checkability(step(EXAMPLES["mode"][0], EXAMPLES["attribute_exists"][0]))
    assert c.level == "partial" and "that an attribute was added" in c.text and c.badge == "Partly checkable"


@pytest.mark.parametrize("kind", ["name_exists", "attribute_exists", "node_count"])
def test_the_text_never_shows_an_internal_kind_name(kind):
    c = checkability(step(EXAMPLES["mode"][0], EXAMPLES[kind][0]))
    assert kind not in c.text and kind not in c.full
    c = checkability(step(EXAMPLES[kind][0]))
    assert kind not in c.text and kind not in c.full


def test_full_joins_the_badge_and_the_explanation():
    c = checkability(step())
    assert c.full == f"{c.badge}. {c.text}" and c.badge == "You confirm"


def test_a_craft_step_says_it_is_judged_by_eye():
    assert "judged by eye" in checkability(step(EXAMPLES["mode"][0], kind="craft")).text
