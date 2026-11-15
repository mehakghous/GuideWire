"""The highlight drawn over the application the learner is working in (Umaima's `vision/overlay.py`).

The overlay is transparent, always on top, never takes focus and lets every click through, so the learner keeps working in Blender; it only draws. It is also hidden from screen capture,
so vision never reads GuideWire's own marks back. Everything here is lazy and failure-proof: with no Windows, no display or no vision packages `show` returns False and the session carries on without a highlight.
"""
from __future__ import annotations

from typing import Any, Callable

Rect4 = tuple[int, int, int, int]


class ScreenGuide:
    def __init__(self, make_overlay: Callable[[], Any] | None = None):
        """`make_overlay()` returns an object with `cover(rect)`, `set_marks(list)`, `show_click_through()`, `hide()`, `close()` (default: vision.overlay.make_overlay_window)."""
        self._make = make_overlay
        self._win: Any = None
        self.error: str | None = None
        self.visible = False

    def _overlay(self):
        if self._win is None and self.error is None:
            try:
                make = self._make
                if make is None:
                    from vision.overlay import make_overlay_window as make
                self._win = make()
            except Exception as e:
                self.error = f"{type(e).__name__}: {str(e)[:80]}"
        return self._win

    def show(self, rect: Rect4, window: Rect4 | None) -> bool:
        """Highlight `rect` (screen pixels). The overlay covers the application's `window` so a moved window carries the mark; without a window nothing is drawn."""
        if window is None:
            self.clear()
            return False
        win = self._overlay()
        if win is None:
            return False
        try:
            from shared.grounding import Rect
            from vision.overlay import highlight_mark
            win.cover(Rect(*window))
            win.set_marks([highlight_mark(Rect(*rect))])
            win.show_click_through()
            self.visible = True
            return True
        except Exception as e:
            self.error = f"{type(e).__name__}: {str(e)[:80]}"
            return False

    def clear(self) -> None:
        if self._win is not None and self.visible:
            try:
                self._win.set_marks([])
                self._win.hide()
            except Exception:
                pass
        self.visible = False

    def close(self) -> None:
        self.clear()
        if self._win is not None:
            try:
                self._win.close()
            except Exception:
                pass
            self._win = None
