"""History-based verification: did the learner just do what the step asked?

The probe reports Blender's recent operators (`history`: [{"id", "name"}], oldest first). Blender keeps
only the last few, so successive reads overlap: `HistoryTracker` turns them into the NEW events only.
`action_matches` then compares an event's display name ("Add Cube") with the step's UI path
("Add > Mesh > Cube"). Pure: no Blender, no screen. Observes only.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from shared.step_record import Action


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def new_events(prev: list[dict], now: list[dict]) -> list[dict]:
    """Events in `now` that were not in `prev` (the latest list overlaps the previous one)."""
    ids = lambda xs: [(e.get("id"), e.get("name")) for e in xs]  # noqa: E731
    p, n = ids(prev), ids(now)
    for k in range(min(len(p), len(n)), -1, -1):
        if k == 0 or p[len(p) - k:] == n[:k]:
            return now[k:]
    return list(now)


class HistoryTracker:
    """Feed it each probe `history`; it returns what happened since the last read. The first read is a
    baseline (nothing the learner did for THIS step yet), so it returns nothing."""

    def __init__(self) -> None:
        self._last: list[dict] | None = None

    def update(self, history: list[dict] | None) -> list[dict]:
        if history is None:
            return []
        fresh = [] if self._last is None else new_events(self._last, history)
        self._last = list(history)
        return fresh

    def reset(self) -> None:
        self._last = None


def action_matches(action: Action, event: dict) -> bool:
    """True if an operator event is plausibly this action. Every word of the operator's display name must
    appear in the action's UI path; a one-word operator must equal the path's last segment."""
    if not action.ui_element:
        return False
    path = _tokens(action.ui_element)
    name = _tokens(event.get("name", ""))
    if not name or not path:
        return False
    if len(name) == 1:
        return name[0] == path[-1]
    return all(t in path for t in name)


def verify_actions(actions: Iterable[Action], events: list[dict]) -> bool | None:
    """True when every action that names a UI element is matched by some event; None when there is
    nothing to judge (no named action or no events), so the caller treats it as unverifiable."""
    named = [a for a in actions if a.ui_element]
    if not named or not events:
        return None
    return all(any(action_matches(a, e) for e in events) for a in named)
