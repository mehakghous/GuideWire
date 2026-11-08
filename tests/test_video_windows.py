"""Extraction in short overlapping clips: the windows, the time shift, the overlap de-duplication, and the request each clip sends. Scripted provider, no network."""
from ingestion.extract import extract_from_video_windows, merge_window_steps, video_windows
from ingestion.providers.fake import ScriptedProvider
from shared.step_record import Step


def test_windows_cover_the_video_overlap_and_never_end_with_a_tiny_clip():
    assert video_windows(50, 60) == [(0, 50)]
    w = video_windows(397, 60, 8)
    assert w[0] == (0, 60) and w[-1][1] == 397 and all(b - a >= 15 for a, b in w)
    assert all(w[i + 1][0] < w[i][1] for i in range(len(w) - 1))                    # consecutive clips overlap
    tail = video_windows(65, 60, 8)
    assert tail == [(0, 65)]                                                         # a 5 s tail is folded into the first clip


def _step(i, goal, start, end):
    return Step(id=f"s{i:02d}", order=i, goal=goal, video_start_s=start, video_end_s=end)


def test_an_action_seen_twice_in_an_overlap_is_kept_once_and_ids_are_renumbered():
    a = [_step(1, "Create the knee joint", 40, 48), _step(2, "Create the ankle joint", 52, 58)]
    b = [_step(1, "Create the ankle joint", 53, 59), _step(2, "Rename the joint to left_ankle", 70, 76)]
    out = merge_window_steps([a, b], 120)
    assert [s.goal for s in out] == ["Create the knee joint", "Create the ankle joint", "Rename the joint to left_ankle"]
    assert [s.id for s in out] == ["s01", "s02", "s03"] and [s.order for s in out] == [1, 2, 3]


def test_two_different_actions_at_the_same_moment_are_both_kept():
    out = merge_window_steps([[_step(1, "Select the hip joint", 10, 12)], [_step(1, "Press E to extrude", 10, 12)]], 60)
    assert len(out) == 2


def raw(*items):
    return {"title": "t", "app_version_tutorial": None, "steps": [
        {"goal": g, "actions": [], "start_state": [], "expected_state": [], "video_start_s": s, "video_end_s": e, "result": "r", "how_to": [], "check": [], "confidence": 0.9,
         "support": "demonstrated", "kind": "mechanics"} for g, s, e in items]}


def test_each_clip_is_requested_with_its_own_fragment_and_times_are_shifted_back():
    p = ScriptedProvider([raw(("Create the hip joint", "00:05", "00:12")), raw(("Create the knee joint", "00:20", "00:30"))])
    sl = extract_from_video_windows(p, "AAAAAAAAAAA", app="maya", duration_s=100.0, window_s=60.0, overlap_s=8.0, prompt_version="v9")
    assert [c["video_url"].split("#t=")[1] for c in p.calls] == ["0,60", "52,100"]
    assert [round(s.video_start_s) for s in sl.steps] == [5, 72] and [s.id for s in sl.steps] == ["s01", "s02"]       # 20 s into the second clip = 72 s
    assert all("MM:SS counted from the START OF THIS CLIP" in c["prompt"] for c in p.calls)
    assert sl.warnings[0].startswith("extracted in 2 windows") and sl.video_duration_s == 100.0


def test_steps_listed_out_of_time_order_twice_are_sorted_as_a_last_resort_instead_of_failing_the_video():
    from ingestion.extract import extract_from_video
    bad = raw(("Create the knee joint", "00:43", "00:50"), ("Create the hip joint", "00:26", "00:33"), ("Create the ankle joint", "01:00", "01:08"))
    p = ScriptedProvider([bad, bad])
    sl = extract_from_video(p, "AAAAAAAAAAA", app="maya", duration_s=100.0, prompt_version="v9")
    assert [s.goal for s in sl.steps] == ["Create the hip joint", "Create the knee joint", "Create the ankle joint"] and [s.id for s in sl.steps] == ["s01", "s02", "s03"]
    assert any("out of time order" in f for s in sl.steps for f in s.flags) and len(p.calls) == 2                  # the model was asked once more first
