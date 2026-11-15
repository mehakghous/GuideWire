"""Finding the application's window by its program (not only its title), and trusting probe.json only while its process lives."""
from __future__ import annotations

import json

from shared.grounding import Rect
from vision import probe_client
from vision.winplatform import WindowInfo, pick_window


def _w(title, w, h, exe, pid=1, minimized=False):
    return WindowInfo(hwnd=pid * 10, title=title, rect=Rect(0, 0, w, h), minimized=minimized, pid=pid, exe=exe)


def test_a_browser_tab_titled_blender_does_not_win_over_blender():
    """Seen live: with the tab "Get Involved - Blender" open, find_window("Blender") returned Chrome (largest) or, with Blender minimized, nothing but Chrome."""
    chrome = _w("Get Involved - Blender - Google Chrome", 1366, 728, "chrome.exe", pid=7)
    blender = _w("(Unsaved) - Blender 5.2.2 LTS", 1000, 600, "blender.exe", pid=9)
    assert pick_window([chrome, blender], "Blender") is chrome                       # title only: the old rule, kept for applications whose program name is not checked yet
    assert pick_window([chrome, blender], "Blender", exe=("blender",)) is blender
    assert pick_window([chrome], "Blender", exe=("blender",)) is None                # Blender closed: say so, do not point at the browser


def test_minimized_windows_and_other_titles_are_skipped_and_the_largest_wins():
    small = _w("a - Blender", 500, 400, "blender.exe", pid=1)
    big = _w("b - Blender", 900, 700, "blender.exe", pid=2)
    gone = _w("c - Blender", 1920, 1080, "blender.exe", pid=3, minimized=True)
    other = _w("Notepad", 2000, 1500, "notepad.exe", pid=4)
    assert pick_window([small, big, gone, other], "Blender", exe=("blender",)) is big


def test_a_given_process_id_selects_that_blender_when_two_are_open():
    one, two = _w("one - Blender", 900, 700, "blender.exe", pid=1), _w("two - Blender", 500, 400, "blender.exe", pid=2)
    assert pick_window([one, two], "Blender", ("blender",), pid=2) is two             # the larger one is not the one running the add-on
    assert pick_window([one, two], "Blender", ("blender",), pid=99) is None


def _info(tmp_path, **extra):
    path = tmp_path / "probe.json"
    path.write_text(json.dumps({"v": 1, "app": "blender", "port": 1, "token": "t", **extra}))
    return str(path)


def test_probe_info_ignores_a_file_left_by_a_dead_process(tmp_path, monkeypatch):
    monkeypatch.setattr(probe_client, "_process_state", lambda pid: (False, ""))
    assert probe_client.probe_info("blender", _info(tmp_path, pid=4242)) is None
    assert probe_client.read_probe(info_path=_info(tmp_path, pid=4242), app="blender") is None     # no connection attempt to a port nobody owns


def test_probe_info_ignores_a_reused_process_id(tmp_path, monkeypatch):
    monkeypatch.setattr(probe_client, "_process_state", lambda pid: (True, "chrome.exe"))        # the number now belongs to a browser
    assert probe_client.probe_info("blender", _info(tmp_path, pid=4242)) is None
    monkeypatch.setattr(probe_client, "_process_state", lambda pid: (True, "blender.exe"))
    assert probe_client.probe_info("blender", _info(tmp_path, pid=4242))["pid"] == 4242


def test_probe_info_trusts_the_file_when_the_process_cannot_be_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(probe_client, "_process_state", lambda pid: (None, ""))                  # not Windows
    assert probe_client.probe_info("blender", _info(tmp_path, pid=4242)) is not None
    assert probe_client.probe_info("blender", _info(tmp_path)) is not None                       # an older add-on wrote no pid
    assert probe_client.probe_info("maya", _info(tmp_path)) is None                              # another application's probe
    assert probe_client.probe_info("blender", str(tmp_path / "missing.json")) is None
