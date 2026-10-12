"""Detect when a matched instruction is NEGATED or merely hypothetical, so "never join the objects" is not turned into a Join step.

Found by the test audit: both the written parser and the transcript parser mapped by operation name only, so
"Do not press Tab" became an Enter/Exit-Edit-Mode step and "you could press Ctrl+J ... but we are not going to do that" became a Join step.
Deliberately narrow: only explicit negation and "if you wanted to" hypotheticals. "Don't forget to press Tab" is a positive instruction.
Everything uncertain stays an instruction (a false negation silently drops a real step, which is the worse error for a transcript).
"""
from __future__ import annotations

import re

_NEG = re.compile(r"\b(?:do not|don'?t|dont|never|avoid|should not|shouldn'?t|must not|mustn'?t|no need to|not going to|won'?t|wouldn'?t|"
                  r"you do not need to|you don'?t need to|you don'?t have to|you do not have to|stop)\b", re.I)
_NOT_NEG = re.compile(r"\b(?:do not|don'?t|dont) (?:forget|worry|hesitate)\b|\bnever ?mind\b|\bnot only\b", re.I)
_HYPO = re.compile(r"\b(?:if you (?:wanted|wished|were to)|you could if|say you wanted)\b", re.I)
_BOUNDARY = re.compile(r"[.;!?]|\bbut\b|\bthen\b|\band then\b|\bnow\b|\binstead\b", re.I)
_AFTER_NEG = re.compile(r"\bbut\b[^.;!?]*\b(?:not going to|won'?t|don'?t|do not|never|not do|wouldn'?t)\b", re.I)


def _tail_before(low: str, lo: int) -> str:
    head = low[:lo]
    parts = _BOUNDARY.split(head)
    return parts[-1] if parts else head


def negated_at(text: str, lo: int, hi: int) -> bool:
    """Is the instruction found at text[lo:hi] negated or hypothetical? Looks at the clause before it and a trailing 'but we won't'."""
    low = text.lower()
    before = _NOT_NEG.sub(" ", _tail_before(low, lo))
    if _NEG.search(before) or _HYPO.search(_tail_before(low, lo)):
        return True
    return bool(_AFTER_NEG.search(low[hi:]))


def clause_negated(clause: str) -> bool:
    """A written clause that tells the reader NOT to do something ('Do not press Tab.')."""
    c = _NOT_NEG.sub(" ", clause.strip().lower())
    return bool(re.match(r"^(?:please\s+)?(?:do not|don'?t|dont|never|avoid|stop|no need to)\b", c)) or bool(_AFTER_NEG.search(c))
