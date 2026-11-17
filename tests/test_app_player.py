"""The embedded player's pure parts (video id, page, version check). The session screen with the video and the steps list was put back to the earlier layout for now (see docs/later.md), so its tests were removed."""
import pytest

pytest.importorskip("PyQt6")                    # the lean CI install has no Qt

from app.ui.player import page_html, video_id_of  # noqa: E402


def test_the_video_id_is_read_from_every_youtube_link_form():
    assert video_id_of("https://www.youtube.com/watch?v=TmhC35PqZvQ") == "TmhC35PqZvQ"
    assert video_id_of("https://youtu.be/TmhC35PqZvQ?t=10") == "TmhC35PqZvQ"
    assert video_id_of("https://www.youtube.com/watch?list=x&v=TmhC35PqZvQ") == "TmhC35PqZvQ"
    assert video_id_of("https://example.com/watch?v=TmhC35PqZvQ") is None and video_id_of(None) is None and video_id_of("") is None


def test_the_player_page_holds_the_official_player_and_the_two_calls_the_window_makes():
    html = page_html("TmhC35PqZvQ", 12.5)
    assert "iframe_api" in html and "TmhC35PqZvQ" in html and "gwSeek" in html and "gwToggle" in html and "12.5" in html


def test_a_webengine_of_another_qt_version_is_refused_before_any_web_view_is_made(monkeypatch):
    """Seen live: WebEngine 6.140 next to Qt 6.12 imports fine and then crashes the whole application when a web view is shown."""
    pytest.importorskip("PyQt6.QtWebEngineWidgets")
    import PyQt6.QtWebEngineCore as core

    from app.ui import player
    monkeypatch.setattr(core, "qWebEngineVersion", lambda: "6.140.0")
    problem = player.web_engine_problem(probe=False)
    assert problem and "does not match" in problem
    from PyQt6.QtCore import QT_VERSION_STR
    monkeypatch.setattr(core, "qWebEngineVersion", lambda: QT_VERSION_STR)
    assert player.web_engine_problem(probe=False) is None

