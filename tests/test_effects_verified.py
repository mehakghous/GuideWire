"""Knowledge-base `effects` (what a feature's step makes and needs) are claims about the application. Each one has a recipe (verification/recipes.py) that does
the step in the REAL application; the real-application tests run it and check the claim. Without the application installed those tests skip; the
coverage test below always runs, so an effect can never be added without a recipe."""
import pytest

from ingestion.rigging_knowledge import load
from verification.recipes import RECIPES
from verification.runner import find_app, run_recipes

APPS = ("blender", "maya", "houdini")


def claims(app):
    return [(e.id, f, eff) for e in load().entries if app in e.apps for f, eff in e.effects.items()]


@pytest.mark.parametrize("app", APPS)
def test_every_effect_has_a_recipe(app):
    missing = [(eid, f) for eid, f, _ in claims(app) if f not in RECIPES[app]]
    assert not missing, f"{app}: effects with no recipe (unverifiable): {missing}"
    assert claims(app), f"{app} has no derived states at all"


@pytest.mark.parametrize("app", APPS)
def test_every_recipe_feature_exists_in_the_catalog_for_the_app(app):
    from ingestion.features import load_catalog
    cat = load_catalog()
    for f in RECIPES[app]:
        assert f in cat and cat.get(f).support_code(app) != "U", (app, f)


def _probe(app):
    if find_app(app) is None:
        pytest.skip(f"{app} is not installed")
    return run_recipes(app, RECIPES[app])


@pytest.fixture(scope="module", params=APPS)
def probed(request):
    return request.param, _probe(request.param)


def test_effects_hold_in_the_real_application(probed):
    app, probe = probed
    for eid, f, eff in claims(app):
        r = probe["results"][f]
        assert "error" not in r, f"{app} recipe {f} failed: {r.get('error')}"
        before, after = r["before"], r["after"]
        for made in eff["makes"]:
            assert made not in before, f"{eid}/{f}: {made} already exists in an empty {app} scene, so it cannot be an effect"
            assert after.get(made, 0) >= 1, f"{eid}/{f}: the recipe did not make {made} in {app} {probe['version']} (scene has {sorted(after)})"
        for need in eff.get("needs", []):
            assert after.get(need, 0) >= 1, f"{eid}/{f}: {need} is not present after the recipe, so the recipe cannot show it is needed"


def test_effect_names_are_in_the_profile_vocabulary():
    from ingestion.profiles import get_profile
    for app in APPS:
        nodes = get_profile(app).nodes
        for eid, f, eff in claims(app):
            for n in eff["makes"] + eff.get("needs", []):
                assert n in nodes, f"{eid}/{f}: {n} is not in the {app} node vocabulary"
