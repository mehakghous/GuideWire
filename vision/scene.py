"""The one reader of the screen: it decides WHEN the pixels must be read again and how much of them, and keeps the words known in between. Pure of Windows and Qt (OCR and layout are injected).

Before this there were three copies of "compare a thumbnail, read what changed" (`VisionService._scene`, the app's `LiveService._scene`, `guide.run_guide`) that disagreed: one compared the MEAN change of the
whole screen (a menu opening is a small area, so it counted as no change and the old words stayed up to 5 s); one needed three changed cells on a 192x108 thumbnail (a toggled checkbox is about two).

Policy, per look:
  * first look, the window moved or was resized, or a periodic refresh is due  -> read the whole window (and find its layout);
  * nothing changed                                                           -> no OCR: the words already known;
  * a small area changed (a menu, a tooltip, a panel)                         -> read that area only (padded) and merge its words into the known ones;
  * most of the window changed                                                -> read the whole window.
A `busy` region (the 3D viewport's drawing area) redraws constantly while the learner orbits or drags, which is not text: when more than BUSY_SHARE of it changed, its changes are ignored. A menu
that opens over the viewport changes a compact part of it, well under that share, so it is still seen.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from shared.grounding import Rect

THUMB = (192, 108)            # (w, h) of the legacy grayscale thumbnail (`vision/guide.py` and its tests); the reader uses READER_THUMB
READER_THUMB = (384, 216)     # finer: a checkbox is about 3x3 cells instead of 2x2
PIXEL_DELTA = 24              # grey-level difference that counts as a changed pixel
MIN_CHANGED_CELLS = 3         # ignore isolated flicker
PAD = 48                      # frame pixels added around a changed area before reading it
FULL_READ_SHARE = 0.4         # more than this share of the window changed: read it all
BUSY_SHARE = 0.35             # more than this share of a busy region changed: it is a redraw, not text
REFRESH_SECONDS = 30.0        # a full read at least this often, so merged partial reads cannot drift
OCR_SCALE_FULL = 2.0          # the same as the OCR's own default
OCR_SCALE_AREA = 2.0


def changed_cells(prev, cur):
    """Boolean map of the cells that changed by more than PIXEL_DELTA, or None when the sizes differ (a new thumbnail size: everything counts as changed)."""
    if prev is None or prev.shape != cur.shape:
        return None
    return abs(prev.astype("int16") - cur.astype("int16")) > PIXEL_DELTA


def box_of(diff, min_cells: int = MIN_CHANGED_CELLS):
    """Bounding box (x0, y0, x1, y1) in cells of the True cells, or None when fewer than `min_cells` changed."""
    if int(diff.sum()) < min_cells:
        return None
    ys, xs = diff.nonzero()
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def changed_box(prev, cur, min_cells: int = MIN_CHANGED_CELLS):
    """Bounding box (x0, y0, x1, y1) in thumbnail cells of what changed, or None if nothing did. The whole thumbnail when there is no previous one."""
    diff = changed_cells(prev, cur)
    if diff is None:
        return (0, 0, cur.shape[1], cur.shape[0])
    return box_of(diff, min_cells)


def union_box(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def box_to_rect(box, frame_w: int, frame_h: int, pad: int = PAD, thumb: tuple[int, int] = THUMB) -> Rect:
    """Thumbnail-cell box -> frame-pixel rect, padded and clipped to the frame."""
    sx, sy = frame_w / thumb[0], frame_h / thumb[1]
    x0, y0 = max(int(box[0] * sx) - pad, 0), max(int(box[1] * sy) - pad, 0)
    x1, y1 = min(int(box[2] * sx) + pad, frame_w), min(int(box[3] * sy) + pad, frame_h)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def merge_words(old: list, new: list, region: Rect) -> list:
    """Words known before, minus those inside the re-read region, plus the freshly read ones."""
    def inside(w) -> bool:
        cx, cy = w.rect.x + w.rect.w // 2, w.rect.y + w.rect.h // 2
        return region.x <= cx < region.x + region.w and region.y <= cy < region.y + region.h
    return [w for w in old if not inside(w)] + new


def drop_busy_changes(diff, busy: list[Rect], frame_w: int, frame_h: int, thumb: tuple[int, int], share: float = BUSY_SHARE):
    """(`diff` with the changes inside each busy region cleared when that region mostly changed, the cleared slices as (y0, y1, x0, x1)). The slices are the places whose reference picture must be
    brought up to date, or the next look would compare against the picture from before the redraw and drop a real change (a menu) as part of it."""
    out = diff.copy()
    dropped = []
    kx, ky = thumb[0] / frame_w, thumb[1] / frame_h
    for r in busy:
        x0, y0 = max(int(r.x * kx), 0), max(int(r.y * ky), 0)
        x1, y1 = min(int((r.x + r.w) * kx) + 1, thumb[0]), min(int((r.y + r.h) * ky) + 1, thumb[1])
        if x1 <= x0 or y1 <= y0:
            continue
        part = out[y0:y1, x0:x1]
        if float(part.mean()) > share:
            part[:] = False
            dropped.append((y0, y1, x0, x1))
    return out, dropped


@dataclass
class Scene:
    """What the screen showed at the last look."""
    words: list = field(default_factory=list)
    layout: Any = None
    how: str = "none"                 # full | area | none : what this look had to read
    box: Rect | None = None           # the frame area that was re-read, for `how == "area"`
    serial: int = 0


@dataclass
class Stats:
    """Counts for the latency harness and tests: how many looks needed how much reading."""
    looks: int = 0
    full: int = 0
    area: int = 0
    none: int = 0
    ocr_ms: float = 0.0


class SceneReader:
    def __init__(self, ocr: Callable[[Any, float], list], layout: Callable[[Any], Any], clock: Callable[[], float] = time.monotonic, thumb: tuple[int, int] = READER_THUMB):
        """`ocr(pixels, scale) -> words` (the Windows OCR in the app), `layout(pixels) -> Layout`. Both are injected, so this is testable with no screen."""
        self._ocr, self._layout, self._clock, self._thumb = ocr, layout, clock, thumb
        self.stats = Stats()
        self.reset()

    def reset(self) -> None:
        """Forget what was read: the next look reads the whole window."""
        self._state: dict[str, Any] | None = None

    @property
    def empty(self) -> bool:
        return self._state is None

    def scene(self) -> Scene | None:
        s = self._state
        return None if s is None else Scene(s["words"], s["layout"], "none", None, s["serial"])

    def read(self, pixels, window: Rect, busy: list[Rect] | None = None, force_full: bool = False) -> Scene:
        """Look at the frame (BGR pixels of the application window) and return the words known now. `window` is where the window sits on the screen: a different one than last time means it moved or
        was resized. `busy` rectangles are in frame pixels. `force_full` reads everything (a caller that knows the interface changed)."""
        import cv2
        h, w = pixels.shape[:2]
        thumb = cv2.resize(cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY), self._thumb, interpolation=cv2.INTER_AREA)
        c = self._state
        now = self._clock()
        self.stats.looks += 1
        box, dropped = None, []
        full = force_full or c is None or c["window"] != window or now - c["full_at"] >= REFRESH_SECONDS
        if not full:
            assert c is not None                                  # `full` is always True without a previous state
            diff = changed_cells(c["thumb"], thumb)
            if diff is None:
                full = True
            else:
                if busy:
                    diff, dropped = drop_busy_changes(diff, busy, w, h, self._thumb)
                box = box_of(diff)
                if box is not None:
                    full = (box[2] - box[0]) * (box[3] - box[1]) / (self._thumb[0] * self._thumb[1]) > FULL_READ_SHARE
        if full:
            layout = self._layout(pixels)
            words = self._timed(lambda: self._ocr(pixels, OCR_SCALE_FULL))
            self._state = {"window": window, "thumb": thumb, "words": words, "layout": layout, "serial": (c or {}).get("serial", 0), "full_at": now}
            self.stats.full += 1
            return Scene(words, layout, "full", Rect(0, 0, w, h), self._state["serial"])
        assert c is not None
        if box is None:
            for y0, y1, x0, x1 in dropped:                        # a redraw was ignored: its reference is brought up to date. Other, small changes keep the old reference, so they add up until they are read
                c["thumb"][y0:y1, x0:x1] = thumb[y0:y1, x0:x1]
            self.stats.none += 1
            return Scene(c["words"], c["layout"], "none", None, c["serial"])
        r = box_to_rect(box, w, h, thumb=self._thumb)
        serial = c["serial"] + 1
        fresh = [replace(wd, rect=type(wd.rect)(wd.rect.x + r.x, wd.rect.y + r.y, wd.rect.w, wd.rect.h), line=wd.line + serial * 100000)
                 for wd in self._timed(lambda: self._ocr(pixels[r.y:r.y + r.h, r.x:r.x + r.w], OCR_SCALE_AREA))]
        words = merge_words(c["words"], fresh, r)
        self._state = {**c, "thumb": thumb, "words": words, "serial": serial}
        self.stats.area += 1
        return Scene(words, c["layout"], "area", r, serial)

    def _timed(self, fn):
        t = time.perf_counter()
        try:
            return fn()
        finally:
            self.stats.ocr_ms += (time.perf_counter() - t) * 1000


def layout_from_model(model, mapper, image_w: int, image_h: int):
    """A `vision.regions.Layout` built from what Blender reported instead of guessed from pixel gaps: viewport, outliner, properties and timeline from the areas, a top bar above the highest area and a
    status bar below the lowest. Confidence 1.0. Rectangles are in captured-image pixels."""
    from vision.regions import Layout, Region, RegionName
    names: dict[str, RegionName] = {"VIEW_3D": "viewport", "OUTLINER": "outliner", "PROPERTIES": "properties", "DOPESHEET_EDITOR": "timeline", "TIMELINE": "timeline"}
    regions, seen = [], set()
    top = image_h
    bottom = 0
    for a in sorted(model.areas, key=lambda a: -(a.rect.w * a.rect.h)):
        r = mapper.to_frame(a.rect)
        top, bottom = min(top, r.y), max(bottom, r.y + r.h)
        name: RegionName = names.get(a.type, "unknown")
        if name in seen:                                       # a second area of the same kind (two 3D views): the first, larger one keeps the name
            name = "unknown"
        seen.add(name)
        regions.append(Region(name, r))
    regions.append(Region("topbar", Rect(0, 0, image_w, max(top, 0))))
    regions.append(Region("statusbar", Rect(0, min(bottom, image_h), image_w, max(image_h - bottom, 0))))
    return Layout(tuple(regions), 1.0)
