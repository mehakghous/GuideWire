# Representative operation set and fixed Blender setup

Everything the team builds is tested against this list. The operations below are the ones **already implemented in the operation catalog** (`ingestion/catalog.py`, 14 entries), so the app, ingestion and vision all use the same ids.

## Operation set (Blender)

| Id | What it is | Kind | Shortcut / menu |
|---|---|---|---|
| `mode.enter_edit` | Enter Edit Mode | procedure | Tab |
| `mode.enter_object` | Return to Object Mode | procedure | Tab |
| `mode.toggle` | Switch between Object Mode and Edit Mode | procedure | Tab |
| `select.object` | Select an object | procedure | click |
| `select.elements` | Select vertices, edges or faces | procedure | 1, 2, 3 |
| `transform.move` | Move | procedure | G |
| `transform.rotate` | Rotate | procedure | R |
| `transform.scale` | Scale | procedure | S |
| `history.undo` | Undo | procedure | Ctrl+Z |
| `history.redo` | Redo | procedure | Ctrl+Shift+Z |
| `object.join` | Join objects | procedure | Ctrl+J |
| `mesh.separate` | Separate selected geometry into a new object | procedure | P |
| `mode.multi_edit` | Edit several mesh objects at once | procedure | Tab |
| `trouble.cross_object_connect` | Why vertices of two objects cannot be connected | troubleshooting | none |

The hand-written sample step files in `shared/examples/` (add a cube and extrude, Subdivision Surface modifier, sculpt draw) also use `add object`, `Extrude Region` and `modifier` steps. If the team wants those in the tested set, they need catalog entries first.

## Fixed Blender version and layout: TO BE DECIDED BY THE TEAM

Nothing in the repo fixes this, so it is not set here. The README still says "write the exact version here".

What the repo does say:
- the knowledge base is built from the Blender manual (`main`, currently the 5.2 LTS manual, with branches for 5.0-5.3, 4.0-4.5, 3.3/3.5/3.6 and 2.93);
- the catalog marks each operation with the versions it was verified against (`verified_versions`, default `main`).

To close this item, the team agrees on **one** installed version (suggest one that the manual branch covers, so facts and screenshots match), then:
1. writes it in `README.md` under "Required versions";
2. uses the default layout at 1920x1080 (or the same display scaling) on every machine, so screenshots are comparable;
3. Umaima takes her reference screenshots on that version.

Decision owner: all three (Mehak, Ayesha, Umaima). Record it here once agreed: **Blender version: ________**
