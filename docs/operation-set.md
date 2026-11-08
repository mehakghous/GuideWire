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

## Fixed application versions and layout

Versions the team works against (installed by Ayesha; Mehak and Umaima must install the same ones):

| Application | Version |
|---|---|
| Blender | 5.2 |
| Maya | 2027 |
| Houdini | 22.0.466 |

- Blender 5.2 matches the manual the knowledge base is built from (`main`, the 5.2 LTS manual), so facts, shortcuts and screenshots line up.
- The operation set above is Blender only. Maya and Houdini operations are covered by the rigging catalog (`ingestion/features.py`).
- Use the default layout at 1920x1080 (or the same display scaling) on every machine, so screenshots are comparable.
- Umaima takes her reference screenshots on these versions.
