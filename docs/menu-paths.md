# Exact menu paths (Blender, Maya, Houdini)

For a question like "how do I add a cube?" GuideWire now says **where to click**, not just which section:

    Where: Add > Mesh > Cube  (3D Viewport header; Object Mode)
    Where: Edge > Bevel Edges  (3D Viewport header; Edit Mode (mesh)). Shortcut: Ctrl+B
           Enter Edit Mode first (select the object, press Tab).
    Where (pick the one you mean): Add > Mesh > Ico Sphere ...; Add > Mesh > UV Sphere ...

## Where the paths come from
Never from memory or by hand. `vision/menus/dump_<app>.py` reads the **real application's own menus** and writes
`shared/menus/<app>_menus.json`. A path is only offered if the menu really contains it. If an application has no
dump, GuideWire says it has no menu path (it does not guess).

| App | Data | Status |
|---|---|---|
| Blender 5.2.3 | `shared/menus/blender_menus.json`: top bar (File, Edit, Render, Window, Help) and the 3D Viewport header menus in Object, Edit (mesh) and Sculpt Mode. 596 items that run a command, 130 with their default shortcut | **Real dump, tested** |
| Maya 2027 | `vision/menus/dump_maya.py` walks the main menus of every menu set (Modeling, Rigging, Animation, FX, Rendering) and records which set each item needs | Script written and tested on a fake Maya; **not yet run in Maya** (not installed) |
| Houdini 22.0.466 | `vision/menus/dump_houdini.py` reads Houdini's own menu XML and the Tab-menu node names per network type | Script written and tested on sample XML and a fake `hou`; **not yet run in Houdini** (not installed) |

Regenerate Blender's file (needs the real Blender window for the keymaps; it opens briefly and closes itself):

    "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --factory-startup --python vision/menus/dump_blender.py -- shared/menus/blender_menus.json

Maya and Houdini: see the docstring at the top of `dump_maya.py` / `dump_houdini.py` (run once in the app's Script
Editor / Python Shell, then spot-check a few paths against the application before committing the JSON).

## How a question becomes a path
1. `shared/menu_paths.py` `find_menu_paths(app, question, mode)`: matches the content words of the question
   (create/make/new/insert all mean "add"; plurals ignored) against the final menu item and its parents.
   Menu items in the learner's current mode are preferred; with no mode given, Object Mode is assumed.
2. Each hit carries the full path, where the menu is, the modes it exists in, the shortcut, and what to do first
   (for example "Enter Edit Mode first").
3. **Several equally good different commands** (UV Sphere or Ico Sphere) are listed for the learner to choose; one is never
   picked silently. Two routes to the *same* command (`Face > Extrude Faces` and `Mesh > Extrude > Extrude Faces`) are not ambiguous.
4. Definition questions ("what is a vertex", "why does ...") get no menu line.

## Where it is used
- **Every chat answer** (`ingestion/service.py` `Service.message`): a `Where:` line is appended when there is a clear answer.
- **Every step** (`ingestion/menu_steps.py`, called from `compose_instructions` and when answers are rendered): the step gets an
  `open_menu` action with the full path (so the on-screen guide can light it up) and a `Menu:` how-to line labelled `catalog`
  (guidance from the application's own menus, not something the tutorial showed). Steps that already have a full path are left alone.
- **The on-screen guide**: `python -m vision.demo --ask "add a cube"` resolves the request and guides File/Add/Mesh/Cube
  as you open each dropdown (`--app maya|houdini` once their data exists).

## Limits
- Blender: only the menus above. Other editors (shader, UV, node editors), right-click menus, Pose/Paint/Curve modes, and menus Blender
  fills in while running (recent files, add-on lists) are not in the dump.
- Matching is word-based: a request with no menu item behind it, or too vague to pick one, gets nothing rather than a guess.
- The exact wording is the English default UI of the version in the dump.
