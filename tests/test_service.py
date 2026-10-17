"""GW-001 (CLI error boundary) and GW-010 (service layer + chat + session persistence). Offline; no model, no network."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ingestion import cli
from ingestion.service import Service, chat
from ingestion.session import from_dict, to_dict

ROOT = Path(__file__).resolve().parent.parent
VTT = ROOT / "tests" / "corpus" / "transcript_synthetic.vtt"
PROC = "Press Tab to enter Edit Mode. Select two vertices. Press G to move them."


def svc(path=None, version="2.80"):
    return Service.open(path, version=version, use_kb=False)


def talk(s, *lines):
    return [s.message(x) for x in lines]


# ============================================================ GW-001: errors are one readable line, exit 2
@pytest.mark.parametrize("argv,needle", [(["transcript", "no_such_file.vtt"], "file not found"),
                                         (["transcript", "README.md"], "no timestamped text"),
                                         (["validate", "pytest.ini"], "not valid JSON"),
                                         (["chat", "--script", "no_such_script.txt"], "file not found")])
def test_bad_input_gives_one_line_and_exit_2_not_a_traceback(argv, needle, capsys):
    assert cli.main(argv) == 2
    err = capsys.readouterr().err
    assert needle in err and "Traceback" not in err and len(err.strip().splitlines()) == 1


def test_a_step_list_that_fails_validation_is_reported_in_one_line(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"steps": [{"goal": ""}]}), encoding="utf-8")
    assert cli.main(["validate", str(bad)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error:") and "Traceback" not in err and len(err.strip().splitlines()) == 1


def test_debug_flag_restores_the_traceback():
    with pytest.raises(FileNotFoundError):
        cli.main(["--debug", "transcript", "no_such_file.vtt"])


def test_the_success_path_is_unchanged(capsys):
    assert cli.main(["validate", str(ROOT / "shared" / "examples" / "blender_cube_extrude.json"), "--version", "2.80"]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "procedure"


# ============================================================ GW-010: service
def test_a_plain_question_before_any_tutorial_uses_the_router():
    r = svc().message("How do I join two objects?")
    assert r["route"] == "standalone" and r["kind"] == "procedure" and r["bundle"]["api_calls"] == 0 and not r["session"]["loaded"]


def test_load_last_then_follow_up_questions_without_restating_the_task():
    s = svc()
    a, loaded, why, where = talk(s, PROC, "/load last", "Why are we doing this step?", "Where can I find that button?")
    assert "/load last" in a["text"] and loaded["route"] == "command" and "Nothing is marked done" in loaded["text"]
    assert why["route"] == "session" and why["intent"] == "why" and "Edit Mode" in why["text"]
    assert where["intent"] == "where" and all(v == "pending" for v in where["session"]["status"].values())


def test_milestone_conversation_load_ask_fail_switch_task_resume(tmp_path):
    # the roadmap's acceptance conversation, through the service
    s = svc(tmp_path / "s.json")
    r = talk(s, PROC, "/load last", "Why are we doing this step?", "Is there a keyboard shortcut instead?", "That didn't work.",
             "Actually I want to learn how to rig a character instead.", "Why?", "resume the tutorial", "Continue")
    why, short, failed, switch, ambiguous, resume, cont = r[2:]
    assert why["route"] == "session" and short["intent"] == "shortcut_alt"
    assert failed["session"]["status"]["s01"] == "failed" and failed["kind"] == "clarification"
    assert switch["route"] == "standalone" and switch["session"]["active"] is False
    assert ambiguous["route"] == "clarify" and "paused" in ambiguous["text"]
    assert resume["route"] == "session" and resume["session"]["active"] is True
    assert cont["intent"] == "continue" and cont["session"]["current"] == "s01"


@pytest.mark.parametrize("q", ["Why are we doing this step?", "What should I do next?", "Continue", "Where can I find that button?", "What if I already completed this step?"])
def test_no_question_asked_through_the_service_completes_a_step(q):
    s = svc()
    talk(s, PROC, "/load last")
    assert set(s.message(q)["session"]["status"].values()) == {"pending"}


def test_pasted_instructions_are_never_labelled_as_a_tutorial_video():
    # regression found while building the chat: catalog procedures cite a tutorial video as documentation, and the session adopted its title
    s = svc()
    talk(s, PROC, "/load last")
    assert "Blender" not in (s.session.tutorial.get("title") or "") and s.session.tutorial["source_type"] == "written"


def test_loading_a_transcript_file_keeps_times_and_names_the_file():
    s = svc()
    r = s.message(f'/load transcript "{VTT}" 100')            # the repo path itself contains spaces
    assert "Loaded 10 steps" in r["text"] and s.session.tutorial["title"] == "transcript_synthetic.vtt"
    t = s.message("What happens at 0:41?")
    assert t["intent"] == "timestamp" and "Object Mode" in t["text"]


def test_commands_report_problems_instead_of_raising():
    s = svc()
    for line in ["/load last", "/load transcript nope.vtt", f'/load steps "{ROOT / "README.md"}"', "/observe mode", "/frobnicate", "/load"]:
        r = s.message(line)
        assert r["route"] == "command" and r["bundle"] is None and r["text"], line
    assert s.message("/load last")["text"].startswith("error:")


def test_observed_state_is_recorded_but_does_not_complete_anything():
    s = svc()
    talk(s, PROC, "/load last")
    r = s.message("/observe mode=EDIT_MESH selected_objects=MESH,MESH")
    assert s.session.observed == {"mode": "EDIT_MESH", "selected_objects": ["MESH", "MESH"]} and set(r["session"]["status"].values()) == {"pending"}
    assert s.message("/observe clear")["session"]["observed"] is None


def test_version_command_is_used_in_answers():
    s = svc(version=None)
    talk(s, PROC, "/load last", "/version 4.2")
    assert "4.2" in s.message("Will this work in my Blender version?")["text"]


def test_reset_forgets_everything():
    s = svc()
    talk(s, PROC, "/load last", "done", "/reset")
    assert s.state()["loaded"] is False and s.message("Why?")["route"] == "standalone"


# ============================================================ persistence
def test_a_conversation_survives_a_restart(tmp_path):
    path = tmp_path / "chat.json"
    a = svc(path)
    talk(a, PROC, "/load last", "I did that", "/observe mode=EDIT_MESH")
    b = svc(path, version=None)                                                      # a new process, same file
    assert b.state()["current"] == "s02" and b.state()["status"] == {"s01": "done", "s02": "pending", "s03": "pending"}
    assert b.session.status_by == {"s01": "user"} and b.session.observed == {"mode": "EDIT_MESH"} and b.session.version == "2.80"
    r = b.message("Can you explain the previous step again?")
    assert r["route"] == "session" and "s01" in r["text"]


def test_saving_is_atomic_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "x" / "chat.json"
    s = svc(path)
    talk(s, PROC, "/load last")
    assert path.exists() and not list(path.parent.glob("*.tmp")) and json.loads(path.read_text(encoding="utf-8"))["format"] == 1


def test_session_round_trip_is_lossless(tmp_path):
    s = svc()
    talk(s, PROC, "/load last", "done", "skip this", "That didn't work.")
    d = to_dict(s.session)
    assert to_dict(from_dict(json.loads(json.dumps(d)))) == d


def test_a_corrupt_or_inconsistent_session_file_is_refused_not_trusted(tmp_path, capsys):
    path = tmp_path / "chat.json"
    s = svc(path)
    talk(s, PROC, "/load last")
    d = json.loads(path.read_text(encoding="utf-8"))
    d["current"] = "s99"
    path.write_text(json.dumps(d), encoding="utf-8")
    assert cli.main(["chat", "--session", str(path), "--script", str(ROOT / "pytest.ini"), "--no-kb"]) == 2
    assert "inconsistent" in capsys.readouterr().err
    path.write_text("{ not json", encoding="utf-8")
    assert cli.main(["chat", "--session", str(path), "--no-kb"]) == 2
    d["format"] = 7
    path.write_text(json.dumps(d), encoding="utf-8")
    assert cli.main(["chat", "--session", str(path), "--no-kb"]) == 2


# ============================================================ the terminal command
def test_chat_command_runs_a_script_and_prints_text(tmp_path):
    script = tmp_path / "in.txt"
    script.write_text("\n".join([PROC, "/load last", "Why?", "/quit", "this line is never read"]), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "ingestion.cli", "chat", "--script", str(script), "--version", "2.80", "--no-kb", "--session", str(tmp_path / "s.json")],
                       capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert r.returncode == 0 and "Loaded 3 steps" in r.stdout and "never read" not in r.stdout and (tmp_path / "s.json").exists()


def test_chat_json_mode_prints_what_a_ui_would_receive(tmp_path):
    out = []
    chat(svc(), [PROC], out=out.append, as_json=True)
    d = json.loads(out[0])
    assert set(d) == {"intent", "route", "kind", "text", "bundle", "session"} and d["bundle"]["kind"] == "procedure"


def test_chat_reads_stdin_when_piped():
    r = subprocess.run([sys.executable, "-m", "ingestion.cli", "chat", "--no-kb"], input="How do I join two objects?\n/state\n", capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert r.returncode == 0 and "Join" in r.stdout and "none loaded" in r.stdout


def test_a_pasted_procedure_has_no_recorded_version_so_the_users_own_version_is_never_echoed_back():
    s = svc(version="4.2")
    talk(s, PROC, "/load last")
    txt = s.message("Will this work in my Blender version?")["text"]
    assert s.session.tutorial["version_hint"] is None and "recorded for Blender" not in txt and "4.2" in txt


def test_paths_with_spaces_work_quoted_and_an_unbalanced_quote_is_reported():
    s = svc()
    assert "Loaded 10 steps" in s.message(f'/load transcript "{VTT}" 100')["text"]
    assert s.message('/load transcript "unclosed')["text"].startswith("error:")


# ============================================================ GW-040: freeze checks must pass on any platform
def test_frozen_hash_check_ignores_line_endings_but_catches_any_content_change(tmp_path):
    import hashlib
    from ingestion.hashing import matches_frozen
    f, h = tmp_path / "ref.json", tmp_path / "ref.sha256"
    crlf = b'{"a": 1,\r\n "b": 2}\r\n'
    h.write_text(hashlib.sha256(crlf).hexdigest() + "  ref.json\n")                  # frozen on Windows
    f.write_bytes(crlf)
    assert matches_frozen(f, h)[0]
    f.write_bytes(crlf.replace(b"\r\n", b"\n"))                                        # the same content checked out on Linux
    assert matches_frozen(f, h)[0]
    f.write_bytes(b'{"a": 1,\n "b": 3}\n')                                             # one character different
    assert not matches_frozen(f, h)[0]


def test_every_frozen_file_in_the_repo_matches_under_lf_endings_too():
    from ingestion.hashing import candidate_hashes
    for jf in list((ROOT / "tests" / "corpus").glob("*.json")) + list((ROOT / "eval_data" / "gold").glob("*.json")):
        sha = jf.with_suffix(".sha256")
        if sha.exists():
            lf = jf.read_bytes().replace(b"\r\n", b"\n")
            assert sha.read_text().split()[0] in candidate_hashes(lf), jf.name


# ============================================================ GW-015: catalog knowledge reaches the steps and the follow-ups
def test_every_pitfall_is_a_real_caveat():
    from ingestion.catalog import BY_ID, PITFALLS
    for op_id, items in PITFALLS.items():
        assert all(p in BY_ID[op_id].caveats for p in items), f"{op_id}: a pitfall no longer matches a caveat; revisit the table"


def test_documentation_gaps_and_vocabulary_notes_are_never_presented_as_user_mistakes():
    from ingestion.catalog import OPERATIONS
    for op in OPERATIONS:
        for p in op.pitfalls:
            assert not any(m in p.lower() for m in ("not stated", "does not say", "does not describe", "not verified", "vocabulary")), (op.id, p)
    assert not any("not stated" in m or "vocabulary" in m for m in svc().message("Press Tab to enter Edit Mode.")["bundle"]["steps"]["steps"][0]["common_mistakes"])


def test_catalog_steps_carry_their_pitfalls_and_no_invented_version_differences():
    steps = {s["goal"]: s for s in svc().message("How do I join two objects?")["bundle"]["steps"]["steps"]}
    join = next(s for s in steps.values() if "Join" in s["goal"])
    assert any("modifiers, constraints" in m for m in join["common_mistakes"])
    assert all(s["version_dependent"] == [] for s in steps.values())             # nothing is recorded, so nothing is claimed


def test_user_text_and_transcript_steps_get_the_same_pitfalls():
    s = svc()
    s.message("Select both cubes. Press Ctrl+J to join them.")
    assert any("modifiers" in m for st in s.last_bundle.steps.steps for m in st.common_mistakes)
    from ingestion.router import route
    b = route(VTT.read_text(encoding="utf-8"), input_type="transcript", duration_s=100, version="2.80")
    assert any(st.common_mistakes for st in b.steps.steps)


def test_a_failed_step_and_a_mistake_report_cite_the_known_pitfalls():
    s = svc()
    talk(s, "Select both cubes. Press Ctrl+J to join them.", "/load last", "done")                 # now on the Join step
    mistake = s.message("I made a mistake. How do I recover?")["text"]
    assert "Ctrl+Z" in mistake and "Known pitfalls" in mistake and "modifiers, constraints" in mistake
    failed = s.message("That didn't work.")["text"]
    assert "commonly go wrong" in failed and "modifiers, constraints" in failed


def test_a_step_without_pitfalls_does_not_invent_any():
    s = svc()
    talk(s, "Press G to move it.", "/load last")
    assert "pitfalls" not in s.message("I made a mistake")["text"].lower() and "commonly go wrong" not in s.message("That didn't work")["text"]


def test_the_version_answer_says_when_no_difference_is_recorded_and_lists_unverified_gaps():
    s = svc(version="4.2")
    talk(s, "Press Tab to enter Edit Mode.", "/load last")
    t = s.message("Will this work in my Blender version?")["text"]
    assert "No difference between Blender versions is recorded" in t and "Not verified" in t and "2.80" in t
