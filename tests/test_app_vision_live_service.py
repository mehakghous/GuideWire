"""The incremental screen reader the app uses (app.vision_bridge.default_service_factory): read only what changed. No screen and no OCR: frames and words are faked."""
from types import SimpleNamespace

import numpy as np
import pytest

from app import vision_bridge as vb
from shared.grounding import Rect

pytest.importorskip("cv2")


@pytest.fixture
def svc(monkeypatch):
    import vision.ocr as ocr
    import vision.regions as regions
    from vision.ocr import Word
    s = vb.default_service_factory("blender")
    s.use_probe = False                                    # hermetic: never read a real add-on that happens to be running
    state = {"rect": Rect(0, 0, 400, 240), "pixels": np.zeros((240, 400, 3), np.uint8), "reads": []}
    s.state = state
    monkeypatch.setattr(s, "_frame", lambda: (SimpleNamespace(rect=state["rect"], hwnd=1), (SimpleNamespace(), state["pixels"])))

    def fake_read(img, scale=1.0):
        state["reads"].append(img.shape[:2])
        return [Word("W%dx%d" % img.shape[:2], Rect(1, 1, 10, 5), 1)]
    monkeypatch.setattr(ocr, "read_text", fake_read)
    monkeypatch.setattr(regions, "detect_layout", lambda px: SimpleNamespace(confidence=1.0))
    monkeypatch.setattr(regions, "default_layout", lambda w, h: SimpleNamespace(confidence=1.0))
    return s


def test_the_first_look_reads_the_whole_window(svc):
    svc._scene()
    assert svc.state["reads"] == [(240, 400)]


def test_an_unchanged_screen_costs_no_ocr(svc):
    svc._scene()
    win, frame, px, words, layout = svc._scene()
    assert svc.state["reads"] == [(240, 400)] and len(words) == 1


def test_a_small_change_reads_only_that_area_and_keeps_the_words_elsewhere(svc):
    _, _, _, first, _ = svc._scene()
    px = svc.state["pixels"].copy()
    px[60:100, 120:200] = 255                                      # a menu opens in one place
    svc.state["pixels"] = px
    _, _, _, words, _ = svc._scene()
    assert len(svc.state["reads"]) == 2
    crop = svc.state["reads"][1]
    assert crop[0] < 240 and crop[1] < 400                         # a crop, not the whole window
    assert any(w.text == "W240x400" for w in words) and any(w.text == "W%dx%d" % crop for w in words)       # the old word outside the area stays; the fresh one is added


def test_a_big_change_or_a_moved_window_reads_everything_again(svc):
    svc._scene()
    svc.state["pixels"] = np.full((240, 400, 3), 200, np.uint8)
    svc._scene()
    assert svc.state["reads"][-1] == (240, 400)
    svc.state["rect"] = Rect(30, 40, 400, 240)
    svc._scene()
    assert svc.state["reads"][-1] == (240, 400) and len(svc.state["reads"]) == 3


def test_no_window_clears_what_was_known(svc, monkeypatch):
    svc._scene()
    monkeypatch.setattr(svc, "_frame", lambda: (None, None))
    assert svc._scene() == (None, None, None, [], None) and svc._reader.empty
