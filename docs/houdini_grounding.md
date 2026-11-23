# Houdini highlighting: what Houdini reports, and the plan (22 Nov 2026)

Measured on this computer with Houdini 22.0.466 Apprentice (it starts here with its licence now; the earlier "No licenses could be found" is gone), 1366×768 screen, the default desktop ("Build").
Method: a temporary startup script (`HOUDINI_SCRIPT_PATH`, so the learner's own settings are untouched) built a small network, recorded what `hou` and Houdini's Qt windows report, and a script outside Houdini captured the window. The capture refuses to run when any window of another program covers Houdini.

## What Houdini reports

| Element | How it is found | Precision |
|---|---|---|
| **Nodes in the network editor** | `NetworkEditor.qtScreenGeometry()` gives the pane on screen; `posToScreen(node.position())` and `posToScreen(position + size)` give the node's tile inside its drawable area | **Exact**: the rectangle drawn from these numbers sits on the node tile (checked on the capture). Mapping: `x = pane.x + lo.x`, `y = pane.y + pane.h − hi.y` (the drawable area is the bottom `screenBounds.height` of the pane; y grows upward) |
| **Panes** | Houdini's Qt windows carry names: `DM_ViewLayout` (viewport), `parmdialog` (parameter pane), `playbar`, `dopesheet`, `StatusMessage`; the network editor's own `qtScreenGeometry()` | Exact rectangles |
| **Which node the parameter pane shows** | `paneTab.currentNode()` on the Parm pane | Exact |
| **That node's parameter labels** | `node.parmTemplateGroup().entries()` (and folders inside) | Exact list, in order |
| **Parameter fields themselves** | **not reported**: Houdini draws them itself, not as Qt widgets | Windows OCR inside the `parmdialog` rectangle read "Method", "Add and Replace", "Pack Output", "Only Pack Unpacked", "Ignore Empty Inputs", "Reload Names" correctly, so matching against the closed label list works |
| **Viewport state** | `SceneViewer.currentState()` (e.g. `objview`) | Exact |
| **Node names drawn in the network editor** | OCR reads them ("Packfolderl" for packfolder1), but the exact tile comes from `posToScreen`, so OCR is not needed there | — |
| **Main menus, shelf tabs and tools** | drawn by Houdini; OCR of the top bars | to be measured |
| **Tab menu** (create a node) | not yet checked | to be measured |
| **"Start Here" dialog** | Houdini's own welcome window covers the centre at every start until "Show This Window on Startup" is turned off; it is not an ordinary Qt top-level window | the guide must say so instead of pointing under it |

## Probe snapshot: built and checked in the real Houdini (23 Nov 2026)

`vision/probes/houdini_probe.py` now serves `ui` (panes with screen rectangles, the shown network's visible nodes with their tiles, the parameter pane's node with its labels in order, the viewport state, the display scale) and `ui_rev` / `scene_rev` counters. Started inside Houdini 22.0.466 on a test network and read from outside with `vision.probe_client.read_probe(app="houdini")`, every rectangle it reported was drawn on a capture of the window. The node tiles (skeleton1, packfolder1), the parameter pane, the viewport and the network editor all sit exactly on what the screen shows. The parameter pane reported `packfolder1` with its 12 labels in order (Parent Folder, Replace Method, Pack Output …). Unit tests with a fake `hou` pin the same numbers (`tests/test_houdini_probe_ui.py`).

## Grounders: built and checked live (23 Nov 2026)

What is built:
- **Target kinds** `node`, `parm`, `pane` (schema 0.16).
- **Resolver** `ingestion/targets_houdini.py`. It resolves 552 of the 672 actions in the recorded v13 Houdini runs; the rest are viewport gizmos, list entries and older node names, with nothing to point at.
- **Grounders** `ground_houdini_node`, `ground_houdini_pane`, `ground_houdini_parm` in `vision/grounders.py`, behind the existing gate.
- **The vision service's Houdini path.** The window must belong to houdini.exe, happrentice.exe or hindie.exe; the context carries the probe's snapshot and the words read.
- **Guide logic.** A Tab part is done once the node the step creates exists; a node part is done once that node is selected.

`scripts/houdini_live_check.py`, run against Houdini 22.0.466 with the probe and a test network, decided:

| Target | Result |
|---|---|
| packfolder1 (by name), a Skeleton (by type) | box exactly on each node tile |
| Tab in the network editor, F in the viewport | the pane as a region, with the key in words |
| parameters Replace Method, Pack Output, Reload Names | box on each row, found by OCR inside the parameter pane and matched to Pack Folder's own labels |
| "Target Pattern" on Pack Folder (no such label) | no box; words only |
| Control Group while the pane shows Pack Folder | no box; "Select the APEX Configure Controls node first" |

Offline: `tests/test_houdini_guidance.py` (11 tests, with the measured snapshot and the OCR words of the real capture).

**Still open:**
- **Starting the probe.** The learner starts it by hand in Houdini's Python Shell; a setup step should do it (audit G-3).
- **Not yet pointed at:** menus, shelf tools and the Tab menu's own list.
- **Not yet tried:** display scaling other than 100%, and a second monitor.
- **The Houdini profile** stays `validated=False` for the Blender-only screen reading. The Houdini path does not depend on it.

## Plan

1. **Probe UI snapshot** (`vision/probes/houdini_probe.py`): add to the state it already serves (on the loopback, with its token) the panes with their screen rectangles, the network editor's path and the visible nodes' screen rectangles, the parameter pane's node and its labels in order, the viewport state, and an interface revision number that changes when any of these changes (for the existing cache). Read live on each request, on Houdini's main thread.
2. **Houdini grounders** (`vision/grounders.py`, behind the existing gate in `vision/verify.py`):
   - a node named by a step: its tile from the probe. Two signals: the probe's rectangle and the node existing. If it is not in the shown network, say which network to open;
   - creating a node: point at the network editor pane ("press Tab here"), a region hint;
   - a parameter: the parameter pane must show the step's node, otherwise point at that node first. Then OCR inside the pane, matched against that node's exact labels. The rectangle is used only when the match is unique and confident;
   - a viewport-state key (F, Enter): the viewport pane as a region hint, with the key in words;
   - menus and shelf: the existing header grounder, with the header rectangles of Houdini's top bars.
3. **Step targets for Houdini** (`ingestion/targets.py`): resolve a step's words to node types (from `knowledge/app_vocab/houdini.json`), parameter labels and keys, as Blender's resolver does.
4. **Live check**: a Houdini version of `scripts/vision_live_suite.py`. Start Houdini with a test network, ask for each target, and compare with the probe's own rectangles (ground truth for nodes and panes) and with OCR boxes for parameters.

The Houdini profile in `vision/apps.py` stays `validated=False` until step 4 passes. Until then the app says Houdini sessions are by hand (audit G-1).
