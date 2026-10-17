"""Offline tests for the knowledge layer. The synthetic fixture under tests/kb_fixture imitates the layout of the manual but contains only text
written for this repository, so no CC-BY-SA text is committed. Tests that need the REAL local index skip when knowledge/kb.sqlite is absent."""
import json
import socket
from pathlib import Path

import pytest

from ingestion.kb.candidates import (
    audit_catalog, candidate_from_hit, candidate_steps, detect_conflicts, is_stale, menus_compatible, mode_predicate, normalise_kbd,
    promote, select_variants, validate_candidate,
)
from ingestion.kb.index import KnowledgeBase, terms
from ingestion.kb.rst import clean_inline, parse_page
from ingestion.router import route
from ingestion.tutorials import load_index, rank
from ingestion.workflows import ReviewedWorkflowStore

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "kb_fixture"
SITE = {"render/cycles/index": "Cycles", "modeling/modifiers/generate/bevel": "Bevel Modifier", "modeling/modifiers/index": "Object Modifiers",
        "sculpt_paint/sculpting/introduction": "Sculpting", "scene_layout/object/editing/join": "Join", "modeling/meshes/editing/edge/bevel": "Bevel"}
TUT = [
    {"id": "AAAAAAAAAAA", "url": "https://www.youtube.com/watch?v=AAAAAAAAAAA", "title": "Select & Transform - Blender 2.80 Fundamentals", "channel": "Blender",
     "duration_s": 666, "licence": "creativeCommon", "captions_flag": True, "chapters": 0, "blender_version_hint": "2.80", "source_tier": "official",
     "keywords": ["select", "selection", "transform", "move", "rotate", "scale"]},
    {"id": "BBBBBBBBBBB", "url": "https://www.youtube.com/watch?v=BBBBBBBBBBB", "title": "Model a Piece of Cake", "channel": "someone", "duration_s": 885,
     "licence": "creativeCommon", "captions_flag": True, "chapters": 0, "blender_version_hint": None, "source_tier": "community", "keywords": ["cake", "beginner", "model"]},
]


@pytest.fixture(scope="module")
def kb(tmp_path_factory):
    db = tmp_path_factory.mktemp("kb") / "kb.sqlite"
    return KnowledgeBase.build({"main": FIX}, db_path=db, site_titles=SITE)


# ----------------------------------------------------------------- rst parsing
def test_clean_inline_roles():
    assert clean_inline("Press :kbd:`Ctrl-J` or use :menuselection:`Object --> Join`.") == "Press Ctrl-J or use Object > Join."
    assert clean_inline("see :doc:`/modeling/modifiers/generate/bevel` and ``code`` and **bold**") == "see bevel and code and bold"


def test_parse_page_reference_labels_and_title():
    pg = parse_page("modeling/meshes/editing/edge/bevel", (FIX / "modeling/meshes/editing/edge/bevel.rst").read_text(encoding="utf-8"))
    assert pg.title == "Bevel" and pg.operators == ["bpy.ops.mesh.bevel"]
    assert pg.reference.modes == ["Edit Mode"]
    assert pg.reference.menus == ["Vertex > Bevel Vertices", "Edge > Bevel Edges"]
    assert pg.reference.shortcuts == [("Shift-Ctrl-B", "Bevel Vertices"), ("Ctrl-B", "Bevel Edges")]
    assert "modeling/modifiers/generate/bevel" in pg.see_also
    assert not any("seealso" in s.text.lower() for s in pg.sections[:1])         # see-also text does not leak into the lead


def test_only_a_page_level_reference_block_counts():
    pg = parse_page("editors/3dview/modes", (FIX / "editors/3dview/modes.rst").read_text(encoding="utf-8"))
    assert pg.reference is None and len(pg.references) == 1                       # the block under 'Mode Locking' describes a sub-feature


@pytest.mark.parametrize("raw,exp", [("Shift-Ctrl-B", ("ctrl+shift+b", "keyboard")), ("Ctrl-J", ("ctrl+j", "keyboard")), ("Period", (".", "keyboard")),
                                     ("Shift-RMB", (None, "mouse")), ("R R", ("r r", "keyboard"))])
def test_normalise_kbd(raw, exp):
    assert normalise_kbd(raw)[1] == exp[1] and (exp[0] is None or normalise_kbd(raw)[0].replace(" ", "") == exp[0].replace(" ", ""))


# ----------------------------------------------------------------- index and search
def test_index_stats_and_stopwords(kb):
    s = kb.stats()
    assert s["pages"] == 7 and s["db_bytes"] > 0 and s["branches"] == ["main"]
    assert terms("How do I bevel an edge?") == ["bevel", "edge"]


def test_search_ranks_the_right_page_and_decides_sufficiency(kb):
    r = kb.search("How do I bevel an edge?")
    assert r.hits[0].path == "modeling/meshes/editing/edge/bevel" and r.sufficient
    assert kb.search("What does proportional editing do?").hits[0].path == "editors/3dview/controls/proportional_editing"
    bad = kb.search("how are hamsters trained")
    assert not bad.sufficient and not bad.outside_index


def test_outside_index_points_at_the_official_page_without_content(kb):
    r = kb.search("How do I render with Cycles?")
    assert r.outside_index and not r.sufficient and r.elsewhere[0] == ("render/cycles/index", "Cycles")
    r2 = kb.search("What does the bevel modifier do?")
    assert r2.outside_index and r2.elsewhere[0][0] == "modeling/modifiers/generate/bevel"


# ----------------------------------------------------------------- candidates, trust, conflicts
def hit(kb, path):
    return kb.get_page(path)


def test_candidate_variants_and_question_selection(kb):
    c = candidate_from_hit(hit(kb, "modeling/meshes/editing/edge/bevel"))
    assert [(v.menu, v.shortcut) for v in c.variants] == [("Vertex > Bevel Vertices", "ctrl+shift+b"), ("Edge > Bevel Edges", "ctrl+b")]
    assert [v.shortcut for v in select_variants(c, "How do I bevel an edge?")] == ["ctrl+b"]
    assert len(select_variants(c, "How do I bevel something?")) == 2                 # undecided: keep both and ask


def test_mode_mapping_is_conservative(kb):
    assert mode_predicate(candidate_from_hit(hit(kb, "modeling/meshes/editing/edge/bevel")))[0].target == "EDIT_MESH"
    assert mode_predicate(candidate_from_hit(hit(kb, "scene_layout/object/editing/join")))[0].target == "OBJECT"
    p, why = mode_predicate(candidate_from_hit(hit(kb, "editors/3dview/controls/proportional_editing")))
    assert p is None and "both" in why                                                  # 'Object and Edit Mode': no single state predicate


def test_candidate_steps_are_doc_reference_unreviewed_and_unverifiable(kb):
    c = candidate_from_hit(hit(kb, "modeling/meshes/editing/edge/bevel"))
    steps, assumptions, questions, notes = candidate_steps(c, "How do I bevel an edge?")
    s = steps[-1]
    assert s.provenance == "doc_reference" and s.support == "unknown" and not s.expected_state and s.verifiable is False
    assert s.source_refs[0] == "doc:modeling/meshes/editing/edge/bevel@main" and any("not reviewed" in a for a in s.assumptions)
    assert [a.verb for a in s.actions] == ["open_menu", "press_keys"] and assumptions and not questions
    _, _, q2, _ = candidate_steps(c, "How do I bevel something?")
    assert q2 and "Which one do you mean" in q2[0]                                      # several variants: ask, do not pick silently


def test_observed_state_adds_a_context_step_only_when_the_prerequisite_is_unmet(kb):
    c = candidate_from_hit(hit(kb, "modeling/meshes/editing/edge/bevel"))
    in_object, *_ = candidate_steps(c, "bevel an edge", observed={"mode": "OBJECT"})
    assert in_object[0].provenance == "catalog_context" and in_object[-1].provenance == "doc_reference"
    in_edit, assumptions, *_ = candidate_steps(c, "bevel an edge", observed={"mode": "EDIT_MESH"})
    assert len(in_edit) == 1 and not assumptions


def test_shortcut_collision_marks_a_candidate_for_review(kb):
    join = validate_candidate(candidate_from_hit(hit(kb, "scene_layout/object/editing/join")), kb)
    assert join.status == "needs_review" and any("Pretend Duplicate" in p for p in join.problems)
    assert validate_candidate(candidate_from_hit(hit(kb, "modeling/meshes/editing/mesh/merge")), kb).status == "auto"


def test_menus_and_conflicts_are_compared_not_merged():
    assert menus_compatible("Mesh > Separate", "Mesh > Separate > Selection")
    assert menus_compatible("Object/Mesh > Transform > Move", "Object/Mesh/Curve/Surface > Transform > Move")
    assert not menus_compatible("Object > Join", "Mesh > Join")
    msgs = detect_conflicts([("catalog", {"ctrl+j"}, {"Object > Join"}), ("manual", {"ctrl+k"}, {"Object > Join"})])
    assert len(msgs) == 1 and "ctrl+j" in msgs[0] and "ctrl+k" in msgs[0]
    assert detect_conflicts([("a", {"p"}, set()), ("b", {"p"}, set())]) == []


def test_audit_finds_agreement_and_gaps(kb):
    res = {a["op"]: a for a in audit_catalog(kb)}
    assert res["object.join"]["status"] == "agree" and res["mesh.separate"]["status"] == "agree"
    assert res["history.undo"]["status"] == "page not indexed"


def test_promotion_needs_a_reviewer_and_records_the_source_hash(kb, tmp_path):
    c = candidate_from_hit(hit(kb, "modeling/meshes/editing/mesh/merge"), sha256="a" * 64)
    store = ReviewedWorkflowStore(tmp_path)
    with pytest.raises(ValueError):
        promote(c, " ", "2.80", store, "op:mesh.merge")
    promote(c, "Ayesha", "2.80", store, "op:mesh.merge")
    sl = store.find("op:mesh.merge", "2.80")
    assert sl is not None and sl.steps[0].review_status == "reviewed" and any(r.startswith("sha256:") for r in sl.steps[0].source_refs)
    assert is_stale("a" * 64, "b" * 64) and not is_stale("a" * 64, "a" * 64)


# ----------------------------------------------------------------- experimental: transcript units mapped to manual pages
def test_doc_mapping_requires_the_speaker_to_name_the_tool(kb):
    from ingestion.transcript_ingest import ingest_transcript
    named = "00:00:01.000 now use the merge tool to join the corners together\n00:00:09.000 done"
    r = ingest_transcript(named, duration_s=20, kb=kb)
    s = r.steplist.steps[0]
    assert s.support == "narrated" and s.provenance == "transcript_rules" and any(x.startswith("doc:") for x in s.source_refs)
    assert any("not reviewed" in a for a in s.assumptions) and s.confidence <= 0.5 and "Mesh > Merge" in s.goal
    unnamed = "00:00:01.000 you can see the merge looks nice here when you select it\n00:00:09.000 done"
    assert ingest_transcript(unnamed, duration_s=20, kb=kb).steplist is None           # a casual mention is not an instruction
    assert ingest_transcript(named, duration_s=20).steplist is None                    # off by default: no index, no mapping


def test_menu_names_come_from_the_manual_reference_blocks(kb):
    names = kb.menu_names()
    assert "Object > Join" in names and "Edge > Bevel Edges" in names and "Mesh > Merge" in names


# ----------------------------------------------------------------- version-aware answers and the CLI
OLD = "blender-v2.93-release"


@pytest.fixture(scope="module")
def kb2(tmp_path_factory):
    db = tmp_path_factory.mktemp("kb2") / "kb.sqlite"
    return KnowledgeBase.build({"main": FIX, OLD: ROOT / "tests" / "kb_fixture_old"}, db_path=db, site_titles=SITE)


def test_older_versions_are_answered_from_the_oldest_branch_when_the_page_exists(kb2):
    old = route("How do I merge vertices?", kb=kb2, version="2.80")
    assert old.steps.steps[-1].goal.startswith("Merge") and "Merge Vertices" in old.steps.steps[-1].goal
    assert OLD in old.version_note and "differs" in old.version_note and old.sources[0].version == OLD
    new = route("How do I merge vertices?", kb=kb2, version="5.0")
    assert "Mesh > Merge" in new.steps.steps[-1].goal and new.version_note is None
    no_page = route("How do I bevel an edge?", kb=kb2, version="2.80")                  # the old branch lacks this page: fall back to main, and say so
    assert OLD not in (no_page.version_note or "") and "may differ" in (no_page.version_note or "")


def test_cli_ask_uses_the_index_when_given(tmp_path, capsys):
    db = tmp_path / "k.sqlite"
    KnowledgeBase.build({"main": FIX}, db_path=db, site_titles=SITE)
    from ingestion.cli import main
    assert main(["ask", "How do I merge vertices?", "--kb", str(db)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["route"] == "docs_index" and out["trust"] == "doc_extracted" and out["api_calls"] == 0
    assert main(["ask", "How do I merge vertices?", "--no-kb", "--kb", str(db)]) == 0
    assert json.loads(capsys.readouterr().out)["route"] != "docs_index"


# ----------------------------------------------------------------- routing with the fixture index
def ask(kb, q, **kw):
    return route(q, kb=kb, tutorials=TUT, **kw)


def test_unfamiliar_howto_is_answered_from_the_reference_block(kb):
    b = ask(kb, "How do I bevel an edge?", version="2.80")
    assert (b.route, b.kind, b.trust) == ("docs_index", "procedure", "doc_extracted")
    assert b.steps.steps[-1].provenance == "doc_reference" and "Ctrl" in b.steps.steps[-1].goal and b.api_calls == 0 and b.network_calls == 0
    assert b.sources[0].licence.startswith("CC-BY-SA") and b.sources[0].url.endswith("edge/bevel.html")
    assert b.version_note and "2.80" in b.version_note                                   # the index is not 2.80: say so
    assert any(e.is_excerpt and e.provenance == "documentation" for e in b.explanations)


def test_concept_is_an_attributed_excerpt_not_steps(kb):
    b = ask(kb, "What does proportional editing do?")
    assert (b.kind, b.trust, b.steps) == ("concept", "doc_passage", None)
    assert b.explanations[0].is_excerpt and b.explanations[0].sources[0].verified_on is not None


def test_catalog_still_wins_for_known_operations(kb):
    b = ask(kb, "How do I join two mesh objects?", version="2.80")
    assert b.route == "catalog" and b.trust in ("none", "catalog") and b.steps.steps[0].provenance == "catalog_template"


def test_outside_index_gives_pointers_and_names_what_is_needed(kb):
    b = ask(kb, "How do I render with Cycles?")
    assert (b.route, b.trust) == ("outside_index", "index_pointer") and b.pointers and "network" in b.needs and b.steps is None
    assert b.pointers[0].url.endswith("render/cycles/index.html") and "not in the local index" in b.fallback_reason


def test_state_dependent_questions_ask_for_state_and_do_not_pretend(kb):
    b = ask(kb, "The Join option is missing from my Object menu.")
    assert (b.kind, b.route) == ("needs_state", "docs_index") and "user_state" in b.needs and len(b.questions) >= 2 and not b.steps
    assert any("only works when" in e.text for e in b.explanations)
    unmet = ask(kb, "The Join option is greyed out.", observed={"mode": "EDIT_MESH", "selected_objects": ["MESH"]})
    assert unmet.unmet_prerequisites


def test_tutorial_discovery_is_separate_from_understanding(kb):
    b = ask(kb, "Is there a good tutorial on selecting and transforming objects?", version="2.80")
    assert b.kind == "tutorial_recommendation" and b.recommendations and b.trust == "tutorial_metadata"
    r = b.recommendations[0]
    assert r.title.startswith("Select & Transform") and r.source_tier == "official" and r.convertible == "needs_user_transcript_or_video_model"
    assert "Not yet converted" in r.note and b.steps is None
    none = ask(kb, "Find me a tutorial for modeling a chair")
    assert none.recommendations == [] and none.trust == "none" and "network" in none.needs and "nothing was called" in " ".join(none.caveats)


def test_project_goals_are_not_forced_through_a_single_page(kb):
    b = ask(kb, "How do I make a low-poly model?")
    assert b.route == "tutorial_index"
    assert ask(kb, "How do I merge vertices?").route == "docs_index"


def test_tutorial_url_needs_a_transcript_or_a_model(kb):
    b = ask(kb, "Turn this tutorial into an interactive workflow: https://www.youtube.com/watch?v=34FBeC9mktE")
    assert (b.route, b.kind) == ("tutorial_import", "needs_model") and set(b.needs) == {"transcript", "model"} and b.steps is None


def test_vague_and_unrelated_requests(kb):
    assert ask(kb, "How do I fix it?").route == "clarify"
    assert ask(kb, "What is the population of Canada?").route == "decline"


def test_no_route_touches_the_network_or_a_model(kb, monkeypatch):
    monkeypatch.setattr(socket, "socket", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    for q in ["How do I bevel an edge?", "What is proportional editing?", "Find me a tutorial for a chair", "How do I render with Cycles?",
              "The Join option is missing", "How do I make a low-poly model?", "Make it better"]:
        b = ask(kb, q)
        assert b.api_calls == 0 and b.network_calls == 0


def test_tutorial_ranking_rules():
    recs, _ = rank("beginner tutorial on selecting and transforming", TUT, "2.80")
    assert recs[0].title.startswith("Select")
    assert rank("modeling a chair", TUT)[0] == []                                       # an unrelated video is never recommended
    far, _ = rank("select", TUT, "4.2")
    assert "may differ" in far[0].note                                                  # version distance is called out


# ----------------------------------------------------------------- real index (skipped when not built) and frozen sets
REAL = ROOT / "knowledge" / "kb.sqlite"
needs_real = pytest.mark.skipif(not REAL.exists(), reason="real knowledge index not built (python -m ingestion.kb.fetch; build_kb)")


def frozen(name):
    from ingestion.hashing import matches_frozen
    ok, _ = matches_frozen(ROOT / "tests" / "corpus" / f"{name}.json", ROOT / "tests" / "corpus" / f"{name}.sha256")
    assert ok, f"{name} changed after it was frozen"


def test_held_out_sets_are_frozen():
    frozen("heldout_questions")
    frozen("heldout_B_questions")


@needs_real
def test_real_index_audit_agrees_with_the_manual_where_it_can_be_checked():
    res = {a["op"]: a for a in audit_catalog(KnowledgeBase(REAL))}
    for op in ("object.join", "mesh.separate", "transform.move", "transform.rotate", "transform.scale"):
        assert res[op]["status"] == "agree", res[op]


@needs_real
def test_real_index_regression_floors_on_the_development_and_post_hoc_sets():
    from ingestion.eval.kb_eval import evaluate_set
    kbr = KnowledgeBase(REAL)
    a = evaluate_set(ROOT / "tests" / "corpus" / "heldout_questions.json", kbr, load_index(), "A")["summary"]
    b = evaluate_set(ROOT / "tests" / "corpus" / "heldout_B_questions.json", kbr, load_index(), "B")["summary"]
    for s in (a, b):                                 # floors measured 2026-10-11; set A is a development set and B was used after its first look
        assert s["class_accuracy"] >= 0.85 and s["false_confidence"]["n"] == 0 and s["model_calls"] == 0 and s["network_calls"] == 0
        assert s["attribution_ok"].split("/")[0] == s["attribution_ok"].split("/")[1] and s["schema_valid"].split("/")[0] == s["schema_valid"].split("/")[1]
    assert a["answer_local_answered"].split("/")[0] == a["answer_local_answered"].split("/")[1]
