"""Run INSIDE Blender (headless): record what every menu holds, so a shortcut can be shown with the menu route that does the same thing ("Shift+A" -> Add; "Alt+P" -> Object > Parent > Clear Parent).

    blender --background --factory-startup --python verification/menuitems_blender.py -- request.json     (request.json: {"out": "<path>"}; scripts/dump_ui_catalog.py --menus does this)

Every Menu class is drawn once with a RECORDING layout in place of Blender's: `layout.operator(...)`, `layout.menu(...)` and the few calls like them are written down instead of drawn. Output:
  menus      {menu id: {"label": "Add", "items": [{"op": "object.armature_add", "text": "Single Bone"} | {"menu": "VIEW3D_MT_armature_add", "text": "Armature"}]}}
  headers    {mode: [{"id": "VIEW3D_MT_add", "text": "Add"}, ...]}   the 3D view header's own menus in each mode, with the text the header shows (the roots of a menu route)
  failed     menus whose draw code needs more context than this headless session has (listed, never guessed)
Only what Blender itself reports is written; nothing is inferred.
"""
import json
import sys

import bpy

req = json.loads(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8").read())
MODES = {"OBJECT": None, "EDIT_ARMATURE": "armature", "POSE": "pose", "EDIT_MESH": "mesh"}


class _Props:
    """What `layout.operator(...)` returns: anything may be assigned to it or read from it."""

    def __setattr__(self, k, v):
        pass

    def __getattr__(self, name):
        return _Props()


class Recorder:
    """Stands in for a UILayout. Records operator and menu entries; everything else is absorbed."""

    def __init__(self, items=None):
        self.items = [] if items is None else items
        self.operator_context = "INVOKE_DEFAULT"

    def __setattr__(self, k, v):
        object.__setattr__(self, k, v)

    # --- entries
    def operator(self, idname, text="", text_ctxt="", translate=True, icon="NONE", **kw):
        self.items.append({"op": idname, "text": text or _op_label(idname)})
        return _Props()

    def operator_enum(self, idname, property="", **kw):
        self.items.append({"op": idname, "text": _op_label(idname), "enum": property})

    def operator_menu_enum(self, idname, property="", text="", **kw):
        self.items.append({"op": idname, "text": text or _op_label(idname), "enum": property, "submenu": True})
        return _Props()

    def menu(self, menu, text="", **kw):
        self.items.append({"menu": menu, "text": text or _menu_label(menu)})

    def menu_contents(self, menu):
        self.items.append({"inline": menu})

    def prop_menu_enum(self, data, property="", text="", **kw):
        self.items.append({"prop": property, "text": text, "submenu": True})

    # --- layout containers return something that records into the same list
    def column(self, *a, **kw):
        return self

    row = split = box = column_flow = grid_flow = menu_pie = column

    def __getattr__(self, name):                     # separator, label, prop, template_*, ... : absorbed
        def absorb(*a, **kw):
            return self
        return absorb


def _op_label(idname):
    try:
        mod, fn = idname.split(".", 1)
        return getattr(getattr(bpy.ops, mod), fn).get_rna_type().name
    except Exception:
        return idname


def _menu_label(menu_id):
    cls = getattr(bpy.types, menu_id, None)
    return getattr(cls, "bl_label", "") or menu_id


class _Self:
    def __init__(self, layout, cls):
        self.layout = layout
        self.bl_label = getattr(cls, "bl_label", "")
        self.bl_idname = getattr(cls, "bl_idname", "")


class _Ctx:
    """The real context, with the mode overridden, so a mode's header menus can be recorded."""

    def __init__(self, mode):
        self._mode = mode

    @property
    def mode(self):
        return self._mode

    def __getattr__(self, name):
        return getattr(bpy.context, name)


def draw(cls, mode=None):
    rec = Recorder()
    cls.draw(_Self(rec, cls), _Ctx(mode) if mode else bpy.context)
    return rec.items


def all_menus():
    for name in dir(bpy.types):
        cls = getattr(bpy.types, name, None)
        try:
            if isinstance(cls, type) and issubclass(cls, bpy.types.Menu) and getattr(cls, "bl_label", ""):
                yield name, cls
        except TypeError:
            continue


def scene_with(active, mode=None):
    """An armature and a mesh in the scene, one of them active, optionally in Edit or Pose Mode: many menus read the active object and its mode."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.object
    bpy.ops.object.armature_add()
    arm = bpy.context.object
    for o in (cube, arm):
        o.select_set(False)
    obj = arm if active == "armature" else cube
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if mode:
        try:
            bpy.ops.object.mode_set(mode=mode)
        except Exception:
            pass


def write():
    menus, errors = {}, {}
    for active, mode in (("armature", None), ("mesh", None), ("armature", "EDIT"), ("armature", "POSE"), ("mesh", "EDIT")):      # a menu is kept from the first scene it draws in; later scenes only fill what the earlier ones could not
        scene_with(active, mode)
        for name, cls in all_menus():
            if name in menus:
                continue
            try:
                menus[name] = {"label": cls.bl_label, "items": draw(cls)}
                errors.pop(name, None)
            except Exception as e:                               # a menu that needs a context this session lacks: recorded as failed, not guessed
                errors[name] = f"{type(e).__name__}: {str(e)[:80]}"
    failed = [{"id": k, "why": v} for k, v in errors.items()]
    scene_with("armature")
    headers = {}
    ed = getattr(bpy.types, "VIEW3D_MT_editor_menus", None)
    for mode in MODES:
        try:
            headers[mode] = [{"id": i["menu"], "text": i["text"]} for i in draw(ed, mode) if "menu" in i]       # the header button's own text ("Add"), not the menu class's label ("Mesh")
        except Exception as e:
            failed.append({"id": f"VIEW3D_MT_editor_menus[{mode}]", "why": f"{type(e).__name__}: {str(e)[:80]}"})
    data = {"app": "blender", "version": bpy.app.version_string, "menus": menus, "headers": headers, "failed": failed}
    with open(req["out"], "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print("menu items:", len(menus), "menus,", len(failed), "failed; headers", {k: len(v) for k, v in headers.items()})


write()
