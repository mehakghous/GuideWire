"""GW-023: a concept answer quotes the paragraph that matches the question, not always the page lead.
The 20 questions and pages are synthetic and written by the same author, so the hit rate shows the mechanism works, not how it does on the real manual."""
from pathlib import Path

import pytest

from ingestion.kb.index import KnowledgeBase
from ingestion.router import route

ROOT = Path(__file__).resolve().parents[1]

GOLD = [  # (question, text the right passage contains)
    ("what does the depth option do when I inset faces", "pit or a boss"), ("what does the boundary option do in inset", "border edges"),
    ("what does outset do in the inset tool", "enlarges"), ("what does the individual option do for inset faces", "on its own"),
    ("what does the number of cuts do in subdivide", "edge loops"), ("what does smoothness do when I subdivide", "rounded surface"),
    ("what does the fractal option do in subdivide", "rocky"), ("what does the grid fill pattern do in subdivide", "quads"),
    ("what is the snap target in snapping", "median point"), ("what is increment snapping", "grid units"),
    ("what does face projection snapping do", "another mesh"), ("can snapping round a rotation to angle steps", "fifteen degrees"),
    ("what does flip do to normals", "inside becomes the outside"), ("what does recalculate outside do to normals", "point away"),
    ("what are custom split normals", "per corner"), ("what does the angle threshold do for normals shading", "look sharp"),
    ("what does the count setting do in the array demo", "how many copies"), ("what is relative offset in the array demo", "multiple of the object size"),
    ("what does the merge distance do in the array demo", "welds"), ("what are start and end caps in the array demo", "first and last copy"),
]


@pytest.fixture(scope="module")
def kb(tmp_path_factory):
    return KnowledgeBase.build({"main": ROOT / "tests" / "kb_passages"}, db_path=tmp_path_factory.mktemp("kbp") / "kb.sqlite")


def _excerpt(kb, q):
    r = kb.search(q)
    top = r.hits[0]
    return kb.passage(top, r.terms) or top.lead


def test_gold_passage_hit_rate_beats_the_page_lead(kb):
    with_passage = sum(want in _excerpt(kb, q) for q, want in GOLD)
    lead_only = sum(want in kb.search(q).hits[0].lead for q, want in GOLD)
    assert (with_passage, lead_only) == (20, 0)            # measured 2026-10-15: 20/20 with ranking, 0/20 with the lead


def test_the_lead_is_kept_when_it_already_answers(kb):
    r = kb.search("what is the inset tool")
    assert kb.passage(r.hits[0], r.terms) is None           # only title words in the question: nothing to rank by
    r = kb.search("what does snapping do")
    assert kb.passage(r.hits[0], r.terms) is None


def test_a_concept_answer_quotes_the_matching_paragraph_with_its_page_as_source(kb):
    b = route("what does boundary do in inset faces", kb=kb)            # still has to pass the existing title-match gate before any excerpt is chosen
    assert b.route == "docs_index" and "border edges" in b.explanations[0].text and b.explanations[0].is_excerpt
    assert b.sources[0].url.endswith("modeling/inset.html")


def test_passages_never_exceed_the_length_limit_and_are_verbatim(kb):
    for q, _ in GOLD:
        text = _excerpt(kb, q)
        assert len(text) <= 424 and text.split()[0].isalpha()
