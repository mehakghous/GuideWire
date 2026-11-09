# Vision (Windows, observe-only)

Vision watches the learner's Blender window and answers two questions for the app. It never sends
input to the application.

| Need | Call | Returns |
|---|---|---|
| Where do I point for this step? | `VisionService.ground("File > Import > Wavefront (.obj)")` | `Guidance` with a `shared.grounding.GroundingResult` (draw only when `status == "ok"`), the screen rect, `complete`, `ambiguous` |
| What state is the app in? | `VisionService.observe()` | dict for `ingestion.evaluator` (`mode`, `workspace`, plus `active_tool`, `selection_types`, `active_object` when the probe runs). A missing key means "not observable" |

## Modules (`vision/`)
- `winplatform.py` Windows window lookup (DWM bounds, DPI), windows stacked above Blender,
  click-through overlay flags, hide-from-capture, passive left-click position.
- `capture.py` screen grab of the window, downscale, mask windows that cover Blender.
- `regions.py` finds Blender's areas (viewport, outliner, properties, timeline, top bar, status bar).
- `ocr.py` Windows built-in OCR (no model download, no network).
- `locate.py` finds a UI path ("Add > Mesh > Cube") on screen; the deepest visible part wins.
- `observe.py` mode and workspace from the screen.
- `overlay.py` PyQt6 click-through highlight that follows the window.
- `guide.py` live guidance: re-reads only the changed screen area, ends when the destination is clicked.
- `blender_addon/guidewire_probe.py` + `probe_client.py` read-only state over loopback with a
  per-session token (protocol v1); probe values override OCR.
- `service.py` the entry point above.

## Run the manual checks (Blender open and in front)
    python -m vision.demo                                  # detect areas and draw them
    python -m vision.demo --follow --seconds 30            # overlay follows a moved/resized window
    python -m vision.demo --locate "Add > Mesh > Cube"     # find and highlight one element
    python -m vision.demo --guide "File > Import > Wavefront (.obj)" --recordable

`--recordable` lets screen recorders see the overlay (it is hidden from capture by default so its
own marks are never read back).

## Limits (known)
- Icon-only controls (toolbar buttons) are not found; they return `None` / not `ok`.
- Tested on Blender 5.2.3, English UI, default theme, 1920x1080 at 150% scaling.
- The screen cannot answer `name_exists`, `attribute_exists`, `node_count`; the probe could.
- Maya 2027 and Houdini 22 adapters are not started.
