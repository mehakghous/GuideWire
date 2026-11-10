"""Find a named UI element on screen from OCR words. Pure: no OCR, capture or window calls.

A step names its target the way the UI shows it ("Add > Mesh > Cube", `Action.ui_element`).
`locate` finds the deepest part of that path that is actually visible and consistent with the
parts before it, so with the Add menu closed it points at "Add", and once the menu is open it
points at "Mesh", then "Cube". A name that appears elsewhere (the object called "Cube" in the
Outliner) does not count unless it sits beside the previous part of the path.

Icon-only controls have no text; they are not found here and `locate` returns None for them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from shared.grounding import Rect
from vision.ocr import Word

MIN_SCORE = 0.85
NEAR = 700        # px: how far a submenu item may be from its parent item
_SEP = re.compile(r"\s*(?:>|›|→|/)\s*")


@dataclass(frozen=True)
class Located:
    rect: Rect          # frame pixels
    matched: str        # the path segment that was found
    depth: int          # 0-based index of that segment in the path
    total: int          # number of segments in the path
    score: float        # text similarity 0..1
    alternatives: int = 0   # other places that matched this part equally well (0 = unambiguous)

    @property
    def complete(self) -> bool:
        """True when the last part of the path (the actual target) is the one found."""
        return self.depth == self.total - 1


def parse_path(ui_element: str) -> list[str]:
    return [s for s in _SEP.split(ui_element.strip()) if s]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9. ]+", "", s.lower()).strip()


def _union(rects: list[Rect]) -> Rect:
    x0 = min(r.x for r in rects)
    y0 = min(r.y for r in rects)
    x1 = max(r.x + r.w for r in rects)
    y1 = max(r.y + r.h for r in rects)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def find_phrase(words: list[Word], phrase: str, within: Rect | None = None,
                min_score: float = MIN_SCORE) -> list[tuple[Rect, float]]:
    """Every place the phrase appears as consecutive words on one line, best score first."""
    target = _norm(phrase)
    n = len(target.split())
    out: list[tuple[Rect, float]] = []
    for i in range(len(words) - n + 1):
        run = words[i:i + n]
        if any(w.line != run[0].line for w in run):
            continue
        rect = _union([w.rect for w in run])
        if within is not None and not (within.contains(rect.x, rect.y)
                                       and within.contains(rect.x + rect.w, rect.y + rect.h)):
            continue
        score = SequenceMatcher(None, _norm(" ".join(w.text for w in run)), target).ratio()
        if score >= min_score:
            out.append((rect, score))
    return sorted(out, key=lambda c: -c[1])


def _beside(prev: Rect, cand: Rect) -> bool:
    """A submenu item opens to the right of, or below, its parent, and close by."""
    dx = cand.x - (prev.x + prev.w)
    dy = cand.y - prev.y
    return dx >= -prev.w and dy >= -prev.h and abs(dx) <= NEAR and abs(dy) <= NEAR


def locate(words: list[Word], ui_element: str, within: Rect | None = None) -> Located | None:
    """The deepest visible, consistent part of the UI path, or None."""
    path = parse_path(ui_element)
    if not path:
        return None
    first = find_phrase(words, path[0], within)
    if not first:
        return None
    ties = sum(1 for _, s in first[1:] if s >= first[0][1] - 1e-9)
    best = Located(first[0][0], path[0], 0, len(path), first[0][1], ties)
    for depth, segment in enumerate(path[1:], start=1):
        nxt = [(r, s) for r, s in find_phrase(words, segment, within) if _beside(best.rect, r)]
        if not nxt:
            break
        # Prefer the candidate nearest the parent item.
        r, s = min(nxt, key=lambda c: abs(c[0].x - best.rect.x) + abs(c[0].y - best.rect.y))
        ties = sum(1 for c in nxt if c[1] >= s - 1e-9 and c[0] != r)
        best = Located(r, segment, depth, len(path), s, ties)
    return best
