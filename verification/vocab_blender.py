"""Run inside Blender: blender -b --factory-startup --python vocab_blender.py -- request.json. Writes the REAL names of this install (nothing is changed)."""
import json
import sys

import bpy

req = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))


def enum(cls, prop):
    return [i.identifier for i in cls.bl_rna.properties[prop].enum_items]


def labels_of(base):
    out = set()
    for name in dir(bpy.types):
        cls = getattr(bpy.types, name, None)
        try:
            if isinstance(cls, type) and issubclass(cls, base):
                lbl = getattr(cls, "bl_label", "") or ""
                if lbl:
                    out.add(lbl)
        except TypeError:
            pass
    return out


def operator_names():
    """Operator names, and the names of their properties and of those properties' enum choices (the redo-panel options: With Automatic Weights, Axis Orientation ...)."""
    out = set()
    for mod_name in dir(bpy.ops):
        mod = getattr(bpy.ops, mod_name)
        for op_name in dir(mod):
            try:
                rna = getattr(mod, op_name).get_rna_type()
                if rna.name:
                    out.add(rna.name)
                for prop in rna.properties:
                    if prop.name:
                        out.add(prop.name)
                    if prop.type == "ENUM":
                        out.update(i.name for i in prop.enum_items if i.name)
            except Exception:
                pass
    return out


def property_names():
    """The UI name of every property of every Blender type (Chain Length, Pole Target, Use Tail ...): what the properties panels show."""
    out = set()
    for name in dir(bpy.types):
        rna = getattr(getattr(bpy.types, name, None), "bl_rna", None)
        if rna is None:
            continue
        try:
            out.update(p.name for p in rna.properties if p.name)
        except Exception:
            pass
    return out


def enum_item_names():
    """The names of every enum choice (render engines, primitive types, modifier and constraint names, pivot points ...): they are what menus and dropdowns show."""
    out = set()
    for name in dir(bpy.types):
        cls = getattr(bpy.types, name, None)
        rna = getattr(cls, "bl_rna", None)
        if rna is None:
            continue
        try:
            for prop in rna.properties:
                if prop.type == "ENUM":
                    for item in prop.enum_items:
                        if item.name:
                            out.add(item.name)
        except Exception:
            pass
    return out


node_types = sorted(set(enum(bpy.types.Object, "type")) | {"CONSTRAINT_" + c for c in enum(bpy.types.Constraint, "type")} | {"MODIFIER_" + m for m in enum(bpy.types.Modifier, "type")} | {"BONE"})
data = {
    "app": "blender", "version": bpy.app.version_string,
    "node_types": node_types,                                  # object types, CONSTRAINT_<type>, MODIFIER_<type> and BONE: exactly the names the harness counts
    "object_types": enum(bpy.types.Object, "type"), "constraint_types": enum(bpy.types.Constraint, "type"), "modifier_types": enum(bpy.types.Modifier, "type"),
    "modes": enum(bpy.types.Object, "mode"),
    "context_modes": enum(bpy.types.Context, "mode"),                # what bpy.context.mode returns: EDIT_MESH, PAINT_WEIGHT ... (the profile and the harness use these)
    "workspaces": sorted(w.name for w in bpy.data.workspaces),
    "ui_names": sorted(labels_of(bpy.types.Menu) | labels_of(bpy.types.Panel) | operator_names() | enum_item_names() | property_names()),
}
json.dump(data, open(req["out"], "w", encoding="utf-8"), indent=0)
