"""Turn a screenshot's text into the `observed` dict that `ingestion.evaluator` reads.

Only keys the screen can actually show are set. An absent key means "not observable", which the
evaluator treats as unverifiable, not as wrong (see ingestion/evaluator.py), so when we are not
sure we leave the key out.
"""
from __future__ import annotations

from typing import Any

from shared.grounding import Rect
from vision.locate import find_phrase
from vision.ocr import Word

# Text of Blender's mode dropdown -> evaluator code. Edit Mode is handled separately: the code
# depends on the object type (EDIT_MESH, EDIT_ARMATURE, ...), which the screen does not show.
_MODES = {
    "Object Mode": "OBJECT", "Sculpt Mode": "SCULPT", "Pose Mode": "POSE",
    "Weight Paint": "PAINT_WEIGHT", "Vertex Paint": "PAINT_VERTEX", "Texture Paint": "PAINT_TEXTURE",
}
WORKSPACES = ("Layout", "Modeling", "Sculpting", "UV Editing", "Texture Paint", "Shading",
              "Animation", "Rendering", "Compositing", "Geometry Nodes", "Scripting")
ACTIVE_TAB_CONTRAST = 6      # luminance levels the active tab must exceed the others by


def observe_mode(words: list[Word], header: Rect | None = None,
                 edit_object_type: str | None = None) -> str | None:
    """Interaction mode read from the viewport header's mode dropdown."""
    for text, code in _MODES.items():
        if find_phrase(words, text, header, min_score=0.9) and (header is not None or text != "Texture Paint"):
            return code
    if find_phrase(words, "Edit Mode", header, min_score=0.9) and edit_object_type:
        return f"EDIT_{edit_object_type.upper()}"
    return None


def observe_workspace(words: list[Word], bgr, strip: Rect) -> str | None:
    """The highlighted workspace tab in the top bar, or None if it cannot be told apart."""
    from vision.regions import luminance
    lum = luminance(bgr)
    seen: list[tuple[float, str]] = []
    for name in WORKSPACES:
        for rect, _ in find_phrase(words, name, strip, min_score=0.9)[:1]:
            y0, y1 = max(rect.y - 2, 0), rect.y + rect.h + 2
            # Sample the tab's own background just left and right of the label.
            band = [lum[y0:y1, max(rect.x - 10, 0):rect.x - 2], lum[y0:y1, rect.x + rect.w + 2:rect.x + rect.w + 10]]
            vals = [float(b.mean()) for b in band if b.size]
            if vals:
                seen.append((sum(vals) / len(vals), name))
    if len(seen) < 2:
        return None
    seen.sort(reverse=True)
    return seen[0][1] if seen[0][0] - seen[1][0] >= ACTIVE_TAB_CONTRAST else None


def observe_blender(words: list[Word], bgr, layout, edit_object_type: str | None = None) -> dict[str, Any]:
    """Observed-state dict for a Blender window from its OCR words and layout."""
    obs: dict[str, Any] = {}
    viewport = layout.get("viewport")
    header = Rect(viewport.x, viewport.y, viewport.w, 60) if viewport else None
    mode = observe_mode(words, header, edit_object_type)
    if mode:
        obs["mode"] = mode
    topbar = layout.get("topbar")
    if topbar:
        ws = observe_workspace(words, bgr, topbar)
        if ws:
            obs["workspace"] = ws
    return obs
