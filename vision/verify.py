"""The gate between "something was found" and "the learner is shown a pointer there". A grounder returns what it found with the evidence it rests on; nothing is drawn or advanced on one weak signal.

Rules (each one exists because a nearby-but-wrong highlight is worse than none):
  * a rectangle for a control (`visible`) is used only when the confidence is at least MIN_CONFIDENCE and, for toolbar tools, at least two independent signals agree (the gap pattern of the cells, the
    add-on's scroll distance, a detected cell, the blue active cell). One signal alone is a guess, however confident it looks;
  * a result whose own evidence says it disagrees with something else (the blue cell is not where the alignment puts the active tool) is never used;
  * a region hint (where to scroll, which column of icons holds a tab) needs less: it points at a part of the window Blender itself reported, not at one control inside it;
  * a result that is nearly good enough earns ONE re-read of the screen before it falls back to words (`recheck`), so a frame caught mid-redraw does not cost the learner a pointer for the whole step.
`GroundCache` keeps a verified result while the interface revision, the scene revision and the words read from the screen are unchanged, so nothing is recomputed for a still screen.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from vision.grounders import AMBIGUOUS, HIDDEN, NOT_OPEN, OFFSCREEN, UNKNOWN, VISIBLE, WORDS, WRONG, Grounded

MIN_CONFIDENCE = 0.75          # a control is pointed at from here
MIN_REGION_CONFIDENCE = 0.5    # a region hint from here
RECHECK_FROM = 0.4             # below the bar but at least this: look again once before giving up
MIN_TOOL_SIGNALS = 2           # independent signals a toolbar cell needs


@dataclass(frozen=True)
class Gated:
    result: Grounded           # what may be shown: the original when it passed, else the same words with no rectangle
    ok: bool                   # a rectangle may be drawn
    recheck: bool              # worth one more fresh read of the screen before falling back to words
    reason: str                # why, in words (also what tests assert)


def _signals(g: Grounded) -> int:
    """Independent signals in a tool result's evidence: one line each, minus the ones that say something disagrees."""
    return sum(1 for e in g.evidence if "NOT" not in e and "disagree" not in e and "stale" not in e)


def gate(g: Grounded) -> Gated:
    """Decide what of a grounder's answer may be used."""
    if g.state in (VISIBLE,) and g.rect is not None:
        if any("NOT" in e or "disagree" in e for e in g.evidence):
            return Gated(_words(g), False, True, "the evidence disagrees with itself")
        if g.kind == "tool" and _signals(g) < MIN_TOOL_SIGNALS:
            return Gated(_words(g), False, g.confidence >= RECHECK_FROM, f"a toolbar cell needs {MIN_TOOL_SIGNALS} agreeing signals, there is {_signals(g)}")
        if g.confidence >= MIN_CONFIDENCE:
            return Gated(g, True, False, "confident and consistent")
        return Gated(_words(g), False, g.confidence >= RECHECK_FROM, f"confidence {g.confidence:.2f} is under {MIN_CONFIDENCE}")
    if g.state in (OFFSCREEN, HIDDEN, WRONG, NOT_OPEN) and g.rect is not None:
        if g.confidence >= MIN_REGION_CONFIDENCE or g.state in (HIDDEN, WRONG):
            return Gated(g, True, False, "a region hint from what Blender reported")
        return Gated(_words(g), False, g.confidence >= RECHECK_FROM, "the region hint is too uncertain")
    if g.state == AMBIGUOUS:
        return Gated(_words(g), False, False, "several equally good places: not pointing at one")
    if g.state in (UNKNOWN, WORDS) or g.rect is None:
        return Gated(_words(g), False, g.state == UNKNOWN and g.confidence >= RECHECK_FROM, "nothing to point at")
    return Gated(_words(g), False, False, "not usable")


def _words(g: Grounded) -> Grounded:
    return replace(g, rect=None)


class GroundCache:
    """A gated result per target, valid while nothing it depends on changed. The key is the target, the add-on's interface and scene revisions, the window rectangle and the serial of the words read from
    the screen (it goes up whenever a read found something new). A change in any of them throws the result away; so does `forget`. Without the add-on the revisions are 0, and the words serial alone carries it."""

    def __init__(self) -> None:
        self._store: dict[Any, Gated] = {}
        self._epoch: Any = None
        self.hits = 0
        self.misses = 0

    def lookup(self, target_key: Any, epoch: Any) -> Gated | None:
        if epoch != self._epoch:
            self._store.clear()
            self._epoch = epoch
        got = self._store.get(target_key)
        if got is None:
            self.misses += 1
        else:
            self.hits += 1
        return got

    def put(self, target_key: Any, epoch: Any, value: Gated) -> None:
        if epoch != self._epoch:
            self._store.clear()
            self._epoch = epoch
        self._store[target_key] = value

    def forget(self) -> None:
        self._store.clear()
        self._epoch = None
