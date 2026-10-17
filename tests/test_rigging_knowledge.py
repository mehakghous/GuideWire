"""The rigging knowledge base: its own rules (sources, tiers, valid features), and the real-world questions it must recognise."""
import copy
import json

import pytest

from ingestion.rigging_knowledge import PATH, Knowledge, KnowledgeError, load

DATA = json.loads(PATH.read_text(encoding="utf-8"))


def test_the_shipped_file_obeys_its_own_rules_and_covers_both_apps():
    k = load()
    assert len(k.entries) >= 14 and {a for e in k.entries for a in e.apps} == {"maya", "blender"}
    assert all(s["url"].startswith("https://") and s["tier"] in ("official", "community", "tutorial") for s in k.sources.values())
    assert sum(s["tier"] == "official" for s in k.sources.values()) >= 12                          # real vendor documentation is the base


def test_every_source_is_used_and_no_url_repeats():
    used = set()
    for e in load().entries:
        for group in (e.outline, e.facts, e.verify, e.mistakes):
            for st in group:
                used |= set(st.sources)
        for t in e.troubleshooting:
            used |= set(t["sources"])
        for c in e.conflicts:
            used |= set(c["sources"])
        for u in e.ui:
            used |= {u.get("source"), u.get("options_source")} - {None}
    urls = [s["url"] for s in DATA["sources"].values()]
    assert len(urls) == len(set(urls)) and used <= set(DATA["sources"])
    assert set(DATA["sources"]) - used <= set()                  # nothing researched was left unused: every source backs a statement


def _broken(mutate):
    d = copy.deepcopy(DATA)
    mutate(d)
    return d


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d["entries"][0]["facts"][0].__setitem__("sources", ["NOPE"]), "unknown source"),
    (lambda d: d["entries"][0]["facts"][0].__setitem__("sources", ["C1"]), "cites no official source"),         # official claim backed only by a forum
    (lambda d: d["entries"][0]["facts"][0].__setitem__("tier", "gospel"), "unknown tier"),
    (lambda d: d["entries"][0]["features"].append("ZZZZ-99"), "unknown feature"),
    (lambda d: d["entries"][0]["apps"].append("unity"), "unknown app"),
    (lambda d: d["entries"][0]["mistakes"][0].__setitem__("sources", []), "needs at least one source"),
    (lambda d: d["entries"].append(copy.deepcopy(d["entries"][0])), "duplicate entry ids"),
])
def test_a_file_that_breaks_its_rules_is_refused(mutate, needle):
    with pytest.raises(KnowledgeError, match=needle):
        Knowledge(_broken(mutate))


def test_conflicting_sources_are_recorded_not_resolved():
    e = {x.id: x for x in load().entries}
    assert e["maya.pole_vector"].conflicts and "disagree" in e["maya.pole_vector"].conflicts[0]["text"]
    assert e["maya.add_attribute"].conflicts


# ------------------------------------------------------------------ the real questions people asked (titles of forum threads and bug reports found in the research, 2026-10-16)
REAL_SYMPTOMS = [
    ("Arm bending wrong way", "maya", "maya.ik_handle"),
    ("Mesh is no longer moving with skeleton", "maya", "maya.bind_skin"),
    ("the skeleton moves but the mesh doesn't", "maya", "maya.bind_skin"),
    ("knee going wonky", "blender", "blender.ik_constraint"),
    ("Character doesn't follow knee pole correctly", "blender", "blender.ik_constraint"),
    ("Inverse Kinematics always at 90 degrees wrong angle", "blender", "blender.ik_constraint"),
    ("Bone Heat Weighting: failed to find solution for one or more bones", "blender", "blender.armature_deform_parent"),
    ("my knee flips when I move the ik handle", "maya", "maya.ik_handle"),
    ("can't rotate joint around x", "maya", "maya.orient_joint"),
]


@pytest.mark.parametrize("text,app,entry", REAL_SYMPTOMS)
def test_real_symptom_wording_finds_the_right_troubleshooting_entry(text, app, entry):
    hit = load().troubleshoot(text, app)
    assert hit is not None and hit[0].id == entry and hit[1]["fix"]


def test_unrelated_or_wrong_app_text_finds_nothing():
    k = load()
    assert k.troubleshoot("what is the weather like", "maya") is None
    assert k.troubleshoot("bone heat weighting failed", "maya") is None            # that is a Blender message
    assert k.troubleshoot("knee flips", "houdini") is None                          # Houdini is not researched: nothing is invented


def test_ui_names_come_from_the_documented_paths_and_options():
    names = load().ui_names("maya")
    assert {"Skeleton", "Orient Joint", "Primary Axis", "Maintain Offset", "Freeze Transformations", "Smooth Bind", "Minimum", "Maximum"} <= names
    assert "Armature Deform" in load().ui_names("blender") and "Chain Length" in load().ui_names("blender")


# ------------------------------------------------------------------ the answer a person gets
def test_a_described_symptom_is_answered_with_cause_fix_trust_and_sources():
    from ingestion.router import route
    b = route("my knee flips when I move the ik handle", app="maya")
    assert b.route == "rigging_knowledge" and b.kind == "troubleshooting"
    assert "Likely cause" in b.explanations[0].text and b.explanations[1].text.startswith("What to try: 1.")
    assert any("Trust: community" in c for c in b.caveats) and all(s.url.startswith("https://") for s in b.sources)
    assert {s.kind for s in b.sources} == {"forum"}                                      # forum advice is labelled as such, not as vendor documentation


def test_official_documentation_is_labelled_as_such_and_the_other_app_is_named_when_it_is_the_one_that_matched():
    from ingestion.router import route
    b = route("can't rotate joint around x", app="maya")
    assert b.sources[0].kind == "manual" and any("Trust: official" in c for c in b.caveats)
    other = route("bone heat weighting failed", app="maya")                               # a Blender message, asked while set to Maya
    assert other.route == "rigging_knowledge" and any("blender advice but you are working in maya" in c for c in other.caveats)


def test_unrelated_questions_and_rigging_procedures_are_not_hijacked():
    from ingestion.router import route
    assert route("what is the best pizza recipe", app="maya").route != "rigging_knowledge"
    assert route("1. Create joints\n2. Create an IK handle", app="maya").route == "rigging_text"
    assert route("How do I switch to Edit Mode?", version="2.80").route != "rigging_knowledge"


def test_cli_ask_answers_a_symptom(capsys):
    from ingestion import cli
    assert cli.main(["ask", "--app", "maya", "--no-kb", "mesh is no longer moving with skeleton"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["route"] == "rigging_knowledge" and "skinCluster" in d["explanations"][1]["text"]


# ------------------------------------------------------------------ everyday requests (a development set written by the assistant AFTER the knowledge base: an upper bound)
def test_everyday_requests_are_understood_with_the_knowledge_base_and_mostly_not_without_it():
    from pathlib import Path
    import ingestion.intent_rigging as IR
    import ingestion.terms as T
    from ingestion.rigging_discovery import parse_goal
    reqs = json.loads((Path(__file__).parent / "fixtures" / "rubrics" / "everyday_requests.json").read_text(encoding="utf-8"))["requests"]

    def hits():
        out = []
        for r in reqs:
            g = parse_goal(r["text"], r["app"])
            out.append((not g.plan and not g.areas) if not r["ok"] else any(f in g.plan for f in r["ok"]))
        return sum(out)
    on = hits()
    IR.USE_KNOWLEDGE = T.USE_KNOWLEDGE = False
    try:
        off = hits()
    finally:
        IR.USE_KNOWLEDGE = T.USE_KNOWLEDGE = True
    assert (off, on) == (9, 16) and on == len(reqs)


# ------------------------------------------------------------------ real spoken tutorials (skipped when the local caption cache is absent: derived YouTube data is not kept in git)
def test_tag_quality_on_real_spoken_tutorials_beats_the_recorded_baseline():
    from pathlib import Path
    from ingestion.eval.speech_tags import load_labels, score_tags
    from ingestion.router import route
    from ingestion.youtube.captions import CACHE_DIR, fetch_captions
    lab = load_labels()
    if not all((Path(CACHE_DIR) / f"{v}.json").exists() for v in lab):
        pytest.skip("real caption cache not present (local_data/captions): fetch with `cli captions <id>` to run this check")
    sls = {v: route(fetch_captions(v).text, input_type="transcript", app=m["app"], duration_s=m["duration_s"]).steps for v, m in lab.items()}
    s = score_tags(sls, lab)
    # the original reader on this label set (last commit, 2026-10-16): precision 42.3%, recall 21.2%
    assert s.precision >= 60.0 and s.recall >= 50.0 and s.false_steps <= 8
