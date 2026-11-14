"""Run inside Blender to write its real menu trees (read-only; nothing in the scene is changed):

    blender -b --factory-startup --python vision/menus/dump_blender.py -- vision/menus/blender_menus.json

Every menu is drawn once into a recording layout that only notes what would be shown: operators,
sub-menus, separators. Item names are exactly what Blender shows (the operator's name unless the menu
gives its own text). Menus that Blender fills in while running (recent files, add-on lists) are not
captured. Context-dependent menus are recorded per interaction mode.
"""
import functools
import json
import sys

import bpy

MAX_DEPTH = 6


class Rec:
    """Stands in for a UILayout: records items, accepts any other call or attribute."""

    def __init__(self, items=None):
        self.items = items if items is not None else []

    def _op_name(self, idname):
        try:
            mod, _, name = idname.partition(".")
            return getattr(getattr(bpy.ops, mod), name).get_rna_type().name
        except Exception:
            return idname

    def operator(self, idname, *args, text="", **kw):
        label = text or self._op_name(idname)
        self.items.append({"label": label, "op": idname})
        return Rec([])

    def operator_menu_enum(self, idname, *args, text="", **kw):
        prop = kw.get("property") or (args[0] if args else "")
        self.items.append({"label": text or self._op_name(idname), "op": idname, "enum": prop})
        return Rec([])

    def operator_enum(self, idname, *args, **kw):
        prop = kw.get("property") or (args[0] if args else "")
        try:
            mod, _, name = idname.partition(".")
            rna = getattr(getattr(bpy.ops, mod), name).get_rna_type()
            for it in rna.properties[prop].enum_items:
                self.items.append({"label": it.name, "op": idname, "enum": f"{prop}={it.identifier}"})
        except Exception:
            pass

    def menu(self, menu_id, *args, text="", **kw):
        self.items.append({"label": text or _menu_label(menu_id), "menu": menu_id})

    def menu_contents(self, menu_id):
        self.items.append({"inline": menu_id})

    def separator(self, **kw):
        return None

    def prop(self, data, *args, text=None, **kw):
        prop = kw.get("property") or (args[0] if args else "")
        if text != "":
            try:
                label = text or data.bl_rna.properties[prop].name
            except Exception:
                label = prop
            self.items.append({"label": label, "prop": prop})

    def label(self, **kw):
        return None

    def row(self, **kw):
        return self

    column = split = box = grid_flow = column_flow = row

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: self

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)


def _menu_class(menu_id):
    return getattr(bpy.types, menu_id, None)


def _menu_label(menu_id):
    cls = _menu_class(menu_id)
    return getattr(cls, "bl_label", None) or menu_id


def _draw(menu_id):
    cls = _menu_class(menu_id)
    if cls is None:
        return []
    rec = Rec()

    class Proxy:
        layout = rec
        bl_label = getattr(cls, "bl_label", "")
        bl_idname = menu_id

        def __getattr__(self, n):
            attr = getattr(cls, n)
            return functools.partial(attr, self) if callable(attr) and not isinstance(attr, type) else attr

    try:
        cls.draw(Proxy(), bpy.context)
    except Exception:
        return rec.items
    return rec.items


def build(menu_id, depth=0, seen=()):
    """The items of one menu, sub-menus expanded, inlined menus merged in place."""
    if depth > MAX_DEPTH or menu_id in seen:
        return []
    out = []
    for it in _draw(menu_id):
        if "inline" in it:
            out.extend(build(it["inline"], depth, seen + (menu_id,)))
        elif "menu" in it:
            out.append({"label": it["label"], "children": build(it["menu"], depth + 1, seen + (menu_id,))})
        else:
            out.append(it)
    return out


def header(menu_id):
    """Top-level entries of an editor header, as they appear left to right."""
    return build(menu_id)


MODES = {"OBJECT": "OBJECT", "EDIT_MESH": "EDIT", "SCULPT": "SCULPT"}     # context.mode -> mode_set name
KEYMAPS = {"OBJECT": ("Object Mode", "3D View", "Window", "Screen"), "EDIT_MESH": ("Mesh", "3D View", "Window", "Screen"),
           "SCULPT": ("Sculpt", "3D View", "Window", "Screen")}


def under_mode(mode):
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
        if mode != "OBJECT":
            bpy.ops.object.mode_set(mode=MODES[mode])
        return bpy.context.mode == mode
    except Exception:
        return False


def shortcuts(mode):
    """operator id -> first shortcut in the keymaps that apply in this mode, e.g. 'Ctrl+J'."""
    out = {}
    cfg = bpy.context.window_manager.keyconfigs.default
    for name in KEYMAPS[mode]:
        km = cfg.keymaps.get(name)
        for kmi in (km.keymap_items if km else []):
            if kmi.active and kmi.value in ("PRESS", "CLICK") and kmi.idname not in out and kmi.type not in (
                    "MOUSEMOVE", "WINDOW_DEACTIVATE", "TIMER", "TEXTINPUT"):
                mods = [m for m, on in (("Ctrl", kmi.ctrl), ("Shift", kmi.shift), ("Alt", kmi.alt), ("Cmd", kmi.oskey)) if on]
                out[kmi.idname] = "+".join(mods + [kmi.type.replace("_", " ").title().replace(" ", "")])
    return out


def annotate(items, keys):
    for it in items:
        if it.get("op") in keys:
            it["keys"] = keys[it["op"]]
        annotate(it.get("children", []), keys)


def main():
    global out
    out = {"app": "blender", "version": bpy.app.version_string, "topbar": header("TOPBAR_MT_editor_menus"), "viewport": {}}
    annotate(out["topbar"], shortcuts("OBJECT"))
    for mode in MODES:
        if under_mode(mode):
            tree = header("VIEW3D_MT_editor_menus")
            annotate(tree, shortcuts(mode))
            out["viewport"][mode] = tree
    under_mode("OBJECT")
    json.dump(out, open(sys.argv[sys.argv.index("--") + 1], "w", encoding="utf-8"), indent=1)
    print("DUMP", "topbar", count(out["topbar"]), {m: count(v) for m, v in out["viewport"].items()}, flush=True)



def count(items):
    return sum(1 + count(i.get("children", [])) for i in items)


def run():
    try:
        main()
    finally:
        if not bpy.app.background:
            bpy.ops.wm.quit_blender()
    return None


if bpy.app.background:
    run()
else:                                   # keymaps (shortcuts) only exist in the full app
    bpy.app.timers.register(run, first_interval=2.0)
