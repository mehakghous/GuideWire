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
- `observe.py` mode, workspace and active tool from the screen.
- `toolbar.py` finds the icon-only toolbar cells from pixels and names them with `toolbars.json`
  (Blender's own tool order per mode, dumped from 5.2.3). A cell holding several tools reports the group
  (`active_tool_candidates`); `active_tool` is set only when the group has one tool.
- `overlay.py` PyQt6 click-through highlight that follows the window.
- `guide.py` live guidance: re-reads only the changed screen area, ends when the destination is clicked.
- `blender_addon/guidewire_probe.py` + `probe_client.py` read-only state over loopback with a
  per-session token (protocol v1). It reports `mode`, `workspace`, `active_tool`, `selection_types`,
  `active_object`, `nodes` / `node_counts` (node types in the scene, same names as
  `verification/collect_blender.py`), `node_names`, and, for paths the caller asks for,
  `properties` and `attributes`. Paths are attribute/index access only (no calls), the same rule as
  `verification/snapshot_blender.py`. Blender is only read on its main thread, so a path asked for the
  first time shows up on the next call. Probe values override OCR.
- `apps.py` per-application profile (window title, pinned version, whether the toolbar logic and a real
  capture check exist). `VisionService(app="maya")` selects it.
- `history.py` history-based verification: `HistoryTracker` turns the probe's operator list into new
  events; `verify_actions` matches them to a step's UI path (camelCase and prefixes handled, so
  `polyCube` matches "Create > Polygon Primitives > Cube").
- `probes/` the Maya and Houdini probes plus the shared loopback server (`probe_core.py`). **Prototypes:
  tested against fake `maya.cmds` / `hou` objects only, never run inside Maya or Houdini.**
- `verification/oracle.py` oracle scorer: compares a learner scene with a reference end state after
  normalising units, up axis and frame rate (Blender Z-up metres, Maya Y-up centimetres, Houdini Y-up
  metres), and drops parts that have no data instead of penalising them.
- `service.py` the entry point above. `observe()` and `ground()` share one capture and one OCR pass while
  the screen is unchanged. `observe(properties=[...], attributes=[...])` passes the active step's paths to the probe.

## Probes per application
| App | Probe | How it reads | History source | Status |
|---|---|---|---|---|
| Blender | `blender_addon/guidewire_probe.py` | `bpy`, on a timer on the main thread | `window_manager.operators` | Run in the real Blender GUI: state, active tool, requested paths. History not checked live |
| Maya | `probes/maya_probe.py` | `maya.cmds`, `executeInMainThreadWithResult` | Script Editor echo file | Prototype, not run in Maya |
| Houdini | `probes/houdini_probe.py` | `hou`, `hdefereval.executeInMainThreadWithResult` | `hou.undos.undoLabels()` | Prototype, not run in Houdini |

All three speak protocol v1 and write their connection details (with the app name) to
`%LOCALAPPDATA%/GuideWire/probe.json`, so run one application at a time. An idle, unfocused Blender
wakes its timers only about every 10 seconds; while someone is working in it they run every 0.5 s.

## Run the manual checks (Blender open and in front)
    python -m vision.demo                                  # detect areas and draw them
    python -m vision.demo --follow --seconds 30            # overlay follows a moved/resized window
    python -m vision.demo --locate "Add > Mesh > Cube"     # find and highlight one element
    python -m vision.demo --guide "File > Import > Wavefront (.obj)" --recordable

`--recordable` lets screen recorders see the overlay (it is hidden from capture by default so its
own marks are never read back).

## Limits (known)
- Toolbar tools are found by position, so a toolbar scrolled out of place can be misread. Other icon-only
  controls (header icons, panel icons) are still not found.
- Edit Mode and other modes' toolbars come from Blender's own tool list but were not checked on a real
  frame; only Object Mode was. Detection was also checked at a sharp 2x enlargement, not on a real 2560x1440 capture.
- Tested on Blender 5.2.3, English UI, default theme, 1920x1080 at 150% scaling.
- `name_exists`, `attribute_exists`, `node_count`, `node_exists`, `property_equals` need the probe add-on
  (the screen cannot read them); `ingestion/evaluator.py` reads them from `node_counts`, `node_names`,
  `attributes`, `nodes` and `properties`. Without the add-on those steps stay unverifiable (manual).
- Maya 2027 and Houdini 22 are not installed on the development machine: their probes and screen
  detection are untested on the real applications (text guidance is app-independent but unchecked there).
