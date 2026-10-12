"""Deterministic timestamp parsing. This is FORMAT conversion only: it never moves a time
into a range it was not in. A value that cannot be parsed raises; it is not guessed."""
from __future__ import annotations

import re

_CLOCK = re.compile(r"^\s*(?:(\d{1,2}):)?(\d{1,3}):([0-5]\d(?:\.\d+)?)\s*$")


def parse_timestamp(v: float | int | str | None) -> float | None:
    """'03:17' -> 197.0, '1:02:03' -> 3723.0, '197' or 197 -> 197.0, None/'' -> None."""
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError(f"not a timestamp: {v!r}")
    if isinstance(v, (int, float)):
        if v < 0:
            raise ValueError(f"negative timestamp: {v}")
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    m = _CLOCK.match(s)
    if m:
        h, mi, sec = m.groups()
        return int(h or 0) * 3600 + int(mi) * 60 + float(sec)
    try:
        f = float(s)
    except ValueError:
        raise ValueError(f"unparseable timestamp: {v!r}") from None
    if f < 0:
        raise ValueError(f"negative timestamp: {v!r}")
    return f
