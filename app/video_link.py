"""The link to a tutorial's video, at the moment a step is shown. No Qt in here.

Only web links are ever opened (http or https): a stored link is data from outside, so a `file:` or other scheme is refused rather than handed to the system.
A YouTube link is rewritten to the plain watch form with the step's start time (`&t=90s`), so "Watch this step in the video" lands on the right second.
"""
from __future__ import annotations

import re

_YOUTUBE = re.compile(r"^(?:https?://)?(?:www\.|m\.|music\.)?(?:youtube\.com/(?:watch\?(?:[^#]*&)?v=|embed/|shorts/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", re.I)
_WEB = re.compile(r"^https?://[^\s]+$", re.I)


def watch_url(url: str | None, start_s: float | None = None) -> str | None:
    """The address to open for a step, or None when there is no safe link."""
    if not url:
        return None
    url = url.strip()
    m = _YOUTUBE.match(url)
    if m:
        at = f"&t={int(start_s)}s" if start_s and start_s >= 1 else ""
        return f"https://www.youtube.com/watch?v={m.group(1)}{at}"
    return url if _WEB.match(url) else None
