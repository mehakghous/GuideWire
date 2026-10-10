"""Run INSIDE Blender to dump the real vocabulary for the installed version:

    blender --background --python scripts/dump_blender_vocab.py -- vocab_blender_<version>.json

STATUS: written from the documented bpy API; NOT yet run (Blender is not installed on the
development machine). Check the output by eye before relying on it. ingestion.profiles.load_overlay()
loads the JSON and only ADDS names to the built-in lists.
"""
import json
import sys

import bpy


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
    out = set()
    for mod_name in dir(bpy.ops):
        mod = getattr(bpy.ops, mod_name)
        for op_name in dir(mod):
            try:
                n = getattr(mod, op_name).get_rna_type().name
                if n:
                    out.add(n)
            except Exception:
                pass
    return out


def enum_items(rna_type, prop):
    return [i.identifier for i in rna_type.bl_rna.properties[prop].enum_items]


data = {
    "blender_version": bpy.app.version_string,
    "ui_names": sorted(labels_of(bpy.types.Menu) | labels_of(bpy.types.Panel) | operator_names()),
    "modes": enum_items(bpy.types.Object, "mode"),
    "editors": enum_items(bpy.types.Area, "ui_type"),
    "workspaces": sorted(w.name for w in bpy.data.workspaces),
}
out_path = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "vocab_blender.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=1)
print("wrote", out_path, {k: len(v) for k, v in data.items() if isinstance(v, list)})
