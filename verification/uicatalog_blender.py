"""Run INSIDE Blender WITH a window (the editor keymaps load only then): blender --factory-startup --python uicatalog_blender.py -- request.json

Writes the STRUCTURE of Blender's interface that GuideWire resolves tutorial words against (nothing in Blender is changed):
  tools      per mode, in toolbar order: groups (one toolbar cell each), separators, and each tool's id, label, operator, keymap name
  operators  id -> label and, for the ones that open a redo panel, their properties (id, label, enum choices)
  panels     Properties editor and other panels: id, label, space, region, context (tab), parent
  menus      every menu class: id and label (a tutorial's "Add > Mesh > Cylinder" starts with one of these labels)
  tabs       the Properties editor tabs: enum id -> label
  keymap     the DEFAULT keymap rows for the 3D view families: keymap name, space, operator, key, modifiers, value, properties
  modes      object interaction modes with the toolbar mode they select
`scripts/dump_ui_catalog.py` runs this and writes knowledge/app_vocab/blender_ui.json. The names in `knowledge/app_vocab/blender.json` stay as they were (a flat list, used by validation).
"""
import json
import sys

import bpy

req = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))

TOOL_MODES = ["OBJECT", "EDIT_MESH", "EDIT_ARMATURE", "EDIT_CURVE", "EDIT_CURVES", "EDIT_SURFACE", "EDIT_METABALL", "EDIT_LATTICE", "EDIT_TEXT", "EDIT_GPENCIL",
              "POSE", "SCULPT", "PAINT_WEIGHT", "PAINT_VERTEX", "PAINT_TEXTURE", "PARTICLE", "SCULPT_CURVES", "PAINT_GREASE_PENCIL", "SCULPT_GREASE_PENCIL", "WEIGHT_GREASE_PENCIL", "VERTEX_GREASE_PENCIL"]
# keymaps that apply inside the 3D viewport (their names are Blender's own; the mode they apply to is in the name or is "any")
KEYMAP_FAMILIES = ("Object Mode", "Mesh", "Armature", "Pose", "Curve", "Curves", "Metaball", "Lattice", "Font", "Sculpt", "Sculpt Curves", "Weight Paint", "Vertex Paint", "Image Paint",
                   "Particle", "Grease Pencil", "3D View", "3D View Generic", "Object Non-modal", "Window", "Screen", "Frames", "Property Editor", "Outliner", "Armature Edit")


def _tool_operator(t):
    """The operator a tool runs. `ToolDef.operator` is empty for most; Blender names a tool's icon after its operator (`ops.mesh.loopcut_slide`), which is the reliable link."""
    if isinstance(t.operator, str) and t.operator:
        return t.operator
    icon = t.icon if isinstance(t.icon, str) else ""
    return icon[4:] if icon.startswith("ops.") else None


def tools():
    from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
    cls = ToolSelectPanelHelper._tool_class_from_space_type("VIEW_3D")
    out = {}
    for mode in TOOL_MODES:
        try:
            items = list(cls.tools_from_context(bpy.context, mode=mode))
        except Exception:
            continue
        rows = []
        for it in items:
            if it is None:
                rows.append({"separator": True})
                continue
            group = it if (isinstance(it, tuple) and not hasattr(it, "idname")) else (it,)
            rows.append({"group": [{"id": t.idname, "label": t.label, "operator": _tool_operator(t),
                                    "keymap": (t.keymap[0] if isinstance(t.keymap, (tuple, list)) and t.keymap and isinstance(t.keymap[0], str) else None),
                                    "icon": t.icon if isinstance(t.icon, str) else None} for t in group if t is not None and hasattr(t, "idname")]})
        if rows:
            out[mode] = rows
    return out


def operators():
    out = {}
    for mod_name in dir(bpy.ops):
        mod = getattr(bpy.ops, mod_name)
        for op_name in dir(mod):
            try:
                rna = getattr(mod, op_name).get_rna_type()
            except Exception:
                continue
            if not rna.name:
                continue
            entry = {"label": rna.name}
            props = []                                        # the properties are what a tutorial sets in the redo panel ("Number of Cuts", "With Automatic Weights"); Blender does not expose which operators open one
            for p in rna.properties:
                if p.identifier == "rna_type" or not p.name:
                    continue
                row = {"id": p.identifier, "label": p.name}
                if p.type == "ENUM":
                    try:
                        row["choices"] = {i.identifier: i.name for i in p.enum_items}
                    except Exception:
                        pass
                props.append(row)
            if props:
                entry["props"] = props
            out[f"{mod_name}.{op_name}"] = entry
    return out


def panels():
    out = []
    for name in dir(bpy.types):
        cls = getattr(bpy.types, name, None)
        try:
            if not (isinstance(cls, type) and issubclass(cls, bpy.types.Panel)):
                continue
        except TypeError:
            continue
        label = getattr(cls, "bl_label", "") or ""
        if not label:
            continue
        out.append({"id": name, "label": label, "space": getattr(cls, "bl_space_type", None), "region": getattr(cls, "bl_region_type", None),
                    "context": getattr(cls, "bl_context", None), "category": getattr(cls, "bl_category", None), "parent": getattr(cls, "bl_parent_id", None)})
    return out


def menus():
    out = []
    for name in dir(bpy.types):
        cls = getattr(bpy.types, name, None)
        try:
            if not (isinstance(cls, type) and issubclass(cls, bpy.types.Menu)):
                continue
        except TypeError:
            continue
        label = getattr(cls, "bl_label", "") or ""
        if label:
            out.append({"id": name, "label": label})
    return out


def tabs():
    try:
        return {i.identifier: i.name for i in bpy.types.SpaceProperties.bl_rna.properties["context"].enum_items}
    except Exception:
        return {}


def keymap():
    rows = []
    kc = bpy.context.window_manager.keyconfigs.user
    for km in kc.keymaps:
        if km.name not in KEYMAP_FAMILIES:
            continue
        for kmi in km.keymap_items:
            if not kmi.active or kmi.type in ("NONE",) or kmi.map_type not in ("KEYBOARD", "MOUSE"):
                continue
            props = {}
            try:
                for k in (kmi.properties.keys() if kmi.properties else []):
                    v = getattr(kmi.properties, k, None)
                    if isinstance(v, (str, int, float, bool)):
                        props[k] = v
            except Exception:
                pass
            rows.append({"keymap": km.name, "space": km.space_type, "op": kmi.idname, "key": kmi.to_string(), "type": kmi.type, "value": kmi.value,
                         "ctrl": bool(kmi.ctrl), "shift": bool(kmi.shift), "alt": bool(kmi.alt), "props": props})
    return rows


def modes():
    return {i.identifier: i.name for i in bpy.types.Object.bl_rna.properties["mode"].enum_items}


def write():
    data = {"app": "blender", "version": bpy.app.version_string, "tools": tools(), "operators": operators(), "panels": panels(), "menus": menus(), "tabs": tabs(), "keymap": keymap(), "modes": modes()}
    with open(req["out"], "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print("ui catalog:", {k: len(v) for k, v in data.items() if isinstance(v, (list, dict))})


if bpy.app.background:
    write()                              # no window: the editor keymaps (Mesh, Object Mode, ...) are NOT loaded, so `keymap` is nearly empty. scripts/dump_ui_catalog.py starts a window for that reason
else:
    def _go():
        try:
            write()
        finally:
            bpy.ops.wm.quit_blender()
    bpy.app.timers.register(_go, first_interval=2.0)
