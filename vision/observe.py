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
    """Interaction mode read from the viewport header's mode dropdown.

    The current mode is the text of the dropdown BUTTON, which is the topmost mode name in the header. When the dropdown is open its list shows
    every mode just below the button, so "any mode name found" would read Object Mode whatever the real mode is; the topmost one is the answer.
    Edit Mode is only reported when the object type is known (EDIT_MESH, EDIT_ARMATURE, ...); otherwise it is "not observable", never another mode."""
    hits: list[tuple[int, int, str]] = []                    # (y, x, code) of the best match of each mode name
    for text, code in _MODES.items():
        if header is None and text == "Texture Paint":
            continue
        found = find_phrase(words, text, header, min_score=0.9)
        if found:
            hits.append((found[0][0].y, found[0][0].x, code))
    edit = find_phrase(words, "Edit Mode", header, min_score=0.9)
    if edit:
        hits.append((edit[0][0].y, edit[0][0].x, "EDIT"))
    if not hits:
        return None
    code = min(hits)[2]                                      # the topmost (then leftmost) mode name is the button
    if code == "EDIT":
        return f"EDIT_{edit_object_type.upper()}" if edit_object_type else None
    return code


def header_row(words: list[Word]) -> Rect | None:
    """A thin strip around the 3D viewport's header row, found from the text itself rather than from a guessed layout.

    That row is the one that holds the "View" and "Select" menus side by side (the topmost such pair; the timeline has View but no Select, the top bar has neither).
    The mode dropdown button sits on this row, left of View. Anchoring on it keeps the workspace tabs above it ("Texture Paint" is a tab name), an open
    dropdown's list below it, and a layout that is off by a title bar or a display scale, all out of the mode reading."""
    pairs = []
    for v in words:
        if v.text != "View":
            continue
        for s in words:
            if s.text == "Select" and s.rect.x > v.rect.x and s.rect.x - v.rect.x < 240 and abs(s.rect.y - v.rect.y) <= 6:
                pairs.append(v)
                break
    if not pairs:
        return None
    top = min(pairs, key=lambda w: (w.rect.y, w.rect.x))
    pad = max(6, top.rect.h // 2)
    return Rect(0, top.rect.y - pad, 10**6, top.rect.h + 2 * pad)


def infer_edit_object_type(words: list[Word], header: Rect | None) -> str | None:
    """The object type being edited, read from the viewport header's menus. In Edit Mode on a mesh the header shows the Mesh, Vertex, Edge and Face
    menus (Object Mode shows Object instead). Only a mesh is recognised; anything else stays unknown, which makes the mode "not observable"."""
    if header is None:
        return None
    return "MESH" if all(find_phrase(words, name, header, min_score=0.9) for name in ("Mesh", "Vertex", "Edge", "Face")) else None


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


def observe_blender(words: list[Word], bgr, layout, edit_object_type: str | None = None,
                    mode_hint: str | None = None) -> dict[str, Any]:
    """Observed-state dict for a Blender window from its OCR words and layout."""
    obs: dict[str, Any] = {}
    viewport = layout.get("viewport")
    guess = Rect(viewport.x, viewport.y, viewport.w, 60) if viewport else None
    header = header_row(words) or guess              # the text's own header row first; the (guessable) layout only when no row can be found
    mode = observe_mode(words, header, edit_object_type or infer_edit_object_type(words, header))
    if mode:
        obs["mode"] = mode
    if viewport:
        from vision.toolbar import find_cells, observe_tool
        known = obs.get("mode") or mode_hint
        if known:
            obs.update(observe_tool(find_cells(bgr, viewport), known))
    topbar = layout.get("topbar")
    if topbar:
        ws = observe_workspace(words, bgr, topbar)
        if ws:
            obs["workspace"] = ws
    return obs
