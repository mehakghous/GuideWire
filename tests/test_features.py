import pytest

from ingestion.features import APPS, SUPPORT_CODES, Catalog, load_catalog


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def test_counts_match_the_specification(cat):
    assert len(cat) == 145
    by_priority = {p: sum(f.priority == p for f in cat.features) for p in ("P0", "P1", "P2", "P3")}
    assert by_priority == {"P0": 16, "P1": 38, "P2": 58, "P3": 33}
    assert len(cat.mvp()) == 51
    assert len({f.code for f in cat.features}) == 22
    assert sorted(f.phase for f in cat.features)[0] == 1 and max(f.phase for f in cat.features) == 5


def test_every_feature_has_a_support_code_for_each_app_and_acceptance_criteria(cat):
    for f in cat.features:
        assert all(f.support_code(a) in SUPPORT_CODES for a in APPS), f.id
        assert f.acceptance and f.outcome and f.workflow, f.id


def test_prerequisites_come_first_and_are_transitive(cat):
    order = [f.id for f in cat.prerequisites("SKIN-03")]
    assert "SKIN-01" in order and "PREP-05" in order and "SKEL-01" in order
    assert order.index("SKEL-01") < order.index("SKIN-01") < len(order)
    assert cat.prerequisites("PREP-01") == []


def test_no_feature_depends_on_a_later_phase(cat):
    for f in cat.features:
        assert all(cat.get(d).phase <= f.phase for d in f.depends_on), f.id


def test_support_queries_follow_the_matrix(cat):
    assert cat.get("LAYR-06").support_code("blender") == "U"            # no native retargeting in Blender
    assert cat.get("LAYR-06") not in cat.supported("blender")
    assert cat.get("ORNT-05") in cat.supported("blender", ("C",))
    assert cat.get("skel-01").id == "SKEL-01"


def test_unknown_ids_and_broken_catalogs_are_rejected(cat):
    with pytest.raises(KeyError):
        cat.get("NOPE-01")
    f = cat.get("PREP-02")
    from dataclasses import replace
    with pytest.raises(ValueError, match="unknown feature"):
        Catalog([replace(f, depends_on=("GHOST-01",))])
    a, b = replace(f, id="AAAA-01", depends_on=("BBBB-01",)), replace(f, id="BBBB-01", depends_on=("AAAA-01",))
    with pytest.raises(ValueError, match="cycle"):
        Catalog([a, b])
