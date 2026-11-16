"""What the learner's HANDS do in a step: the keys to press. Pure: no screen, no vision, no Qt.

This module used to also decide WHAT to point at, from words in the step's text (a list of words that "name scene items", a list of panels that "open at the bottom left", a table of tool keys). That guessing
is gone: the resolver (`ingestion/targets.py`) turns the words into typed targets once, the grounders (`vision/grounders.py`) locate them, and `app/step_state.py` decides what to show.
"""
from __future__ import annotations

import re

from shared.step_record import Step

# words that are keys when they follow "press" in a how-to line ("Press Delete", "Press Ctrl+P")
KEY_WORDS = {"delete", "tab", "enter", "return", "esc", "escape", "space", "backspace", "home", "end", "ctrl", "shift", "alt", "x", "z"}
_KEY = re.compile(r"\bpress(?:ing)?\s+((?:(?:ctrl|shift|alt)\s*\+\s*)*[a-z0-9]+)", re.I)


def keys_of(step: Step) -> tuple[str, ...]:
    """The keys the step says to press, in order, as written on a keyboard ("A", "Delete", "Ctrl+P")."""
    out: list[str] = []
    for a in getattr(step, "actions", []) or []:                       # the step's own key actions say it exactly (["Ctrl", "P"] = Ctrl+P)
        if a.verb == "press_keys" and a.keys:
            out.append("+".join(k if len(k) > 1 else k.upper() for k in a.keys))
    if out:
        return tuple(out)
    for h in step.how_to:
        for m in _KEY.finditer(h.text):
            parts = [p.strip() for p in m.group(1).split("+") if p.strip()]
            if not parts or not all(len(p) == 1 or p.lower() in KEY_WORDS or re.fullmatch(r"f\d{1,2}", p.lower()) for p in parts):
                continue
            out.append("+".join(p.upper() if len(p) == 1 else p.capitalize() for p in parts))
    return tuple(out)
