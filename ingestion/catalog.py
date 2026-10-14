"""Operation catalog: a small, structured, hand-curated registry of well-defined Blender operations.

This is deliberately NOT a documentation index, vector store or search engine. For the dozen operations the
first tutorial and the FYP scope need, a typed registry with aliases is enough, is fully testable offline, and
every entry says exactly what it rests on.

Source policy (see docs/ingestion-technical-plan.md, section 'Knowledge layer'):
- Facts were read on 2026-10-11 from the Blender manual's own source files (branch `main`, currently the
  Blender 5.2 LTS manual). The manual text is CC-BY-SA 4.0; reuse requires credit to the Blender Documentation
  Team and a link. This file stores short paraphrases and facts (shortcuts, menu paths, prerequisites), not
  copied pages, and carries the credit in every SourceRef.
- The tutorial video (Blender 2.80) is cited only for behaviour visible in it, per the assistant-read reference v1.
- Anything not confirmed is listed in `unverified` and is surfaced to the user as a caveat; nothing is invented.
- Version 2.80 itself could NOT be checked against the 2.80 manual (the branch path was not found), so for a
  2.80 install every entry is reported as 'documented for the current manual; this version unverified'.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Callable

from shared.answer import SourceRef
from shared.step_record import Action, StatePredicate as P

VERIFIED_ON = "2026-10-11"
_LICENCE = "CC-BY-SA 4.0, credit: Blender Documentation Team"
_MAIN = "main (Blender 5.2 LTS manual)"


def manual(title: str, path: str, file_read: str) -> SourceRef:
    """A manual page. `file_read` is the manual source file actually read on VERIFIED_ON."""
    return SourceRef(kind="manual", title=f"Blender Manual: {title}",
                     url=f"https://docs.blender.org/manual/en/latest/{path}.html", version=f"{_MAIN}; source file {file_read}",
                     verified_on=VERIFIED_ON, licence=_LICENCE)


TUTORIAL = SourceRef(
    kind="tutorial_video", title="Object and Edit Mode - Blender 2.80 Fundamentals (Blender, CC)",
    url="https://www.youtube.com/watch?v=34FBeC9mktE", version="Blender 2.80",
    verified_on=VERIFIED_ON, licence="YouTube licence field: creativeCommon",
)


@dataclass(frozen=True)
class Prereq:
    text: str
    material: bool = True                 # does it change whether the procedure works?
    predicate: P | None = None            # checked against OBSERVED state when that state is available
    check: Callable[[dict], bool | None] | None = None   # None = cannot be told from the observed state
    established_by: str | None = None     # catalog op whose steps would establish it


@dataclass(frozen=True)
class StepT:
    goal: str
    actions: tuple[Action, ...]
    start_state: tuple[P, ...] = ()
    expected_state: tuple[P, ...] = ()
    alternatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class Operation:
    id: str
    title: str
    kind: str                              # "procedure" | "troubleshooting"
    aliases: tuple[tuple[str, ...], ...]   # OR of AND-groups of lowercase words
    explanation: str                       # the app's own concise wording
    how_to: tuple[StepT, ...]
    clause: StepT | None                   # the single step used when this op appears in written text
    prerequisites: tuple[Prereq, ...] = ()
    applies_to: tuple[str, ...] = ()
    shortcuts: tuple[str, ...] = ()        # normalised: "tab", "ctrl+z"
    menu_paths: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    sources: tuple[SourceRef, ...] = ()
    min_version: tuple[int, int] = (2, 80)
    verified_versions: tuple[str, ...] = ("main",)
    unverified: tuple[str, ...] = ()
    pitfalls: tuple[str, ...] = ()               # things that commonly go wrong with this operation (a subset of `caveats`, same wording) -> Step.common_mistakes
    version_differences: tuple[str, ...] = ()    # documented behaviour that DIFFERS between Blender versions -> Step.version_dependent. Empty for every entry today:
    #                                              no catalog entry has a recorded cross-version difference (`unverified` is a verification gap, not a difference)
    triggers: tuple[tuple[str, ...], ...] = ()   # troubleshooting only
    remedy_op: str | None = None

    @property
    def needs_mode(self) -> str | None:
        return next((p.target for p in (self.clause.start_state if self.clause else ()) if p.kind == "mode"), None)

    @property
    def sets_mode(self) -> str | None:
        return next((p.target for p in (self.clause.expected_state if self.clause else ()) if p.kind == "mode"), None)


def A(verb, ui=None, keys=(), value=None) -> Action:
    return Action(verb=verb, ui_element=ui, keys=list(keys), value=value)


def _selected(obs: dict) -> bool | None:
    sel = obs.get("selected_objects")
    return None if sel is None else len(sel) >= 1


def _join_ok(obs: dict) -> bool | None:
    sel = obs.get("selected_objects")
    if sel is None:
        return None
    return len(sel) >= 2 and len(set(sel)) == 1 and sel[0] in ("MESH", "CURVE", "SURFACE", "ARMATURE")


def _editable_active(obs: dict) -> bool | None:
    sel = obs.get("selected_objects")
    return None if sel is None else any(t in ("MESH", "CURVE", "SURFACE") for t in sel)


OBJ, EDIT = P(kind="mode", target="OBJECT"), P(kind="mode", target="EDIT_MESH")

_MODES = manual("Object Modes", "editors/3dview/modes", "manual/editors/3dview/modes.rst")
_JOIN = manual("Join", "scene_layout/object/editing/join", "manual/scene_layout/object/editing/join.rst")
_SEP = manual("Separate", "modeling/meshes/editing/mesh/separate", "manual/modeling/meshes/editing/mesh/separate.rst")
_UNDO = manual("Undo & Redo", "interface/undo_redo", "manual/interface/undo_redo.rst")
_XFORM = manual("Transform: Introduction", "scene_layout/object/editing/transform/introduction",
                "manual/scene_layout/object/editing/transform/introduction.rst")
_MOVE = manual("Move", "scene_layout/object/editing/transform/move", "manual/scene_layout/object/editing/transform/move.rst")
_ROT = manual("Rotate", "scene_layout/object/editing/transform/rotate", "manual/scene_layout/object/editing/transform/rotate.rst")
_SCALE = manual("Scale", "scene_layout/object/editing/transform/scale", "manual/scene_layout/object/editing/transform/scale.rst")
_SELECT = manual("Selecting (meshes): Introduction", "modeling/meshes/selecting/introduction",
                 "manual/modeling/meshes/selecting/introduction.rst")

_V280 = "Behaviour in Blender 2.80 is confirmed only by the tutorial video (reference v1, assistant-read), not by the 2.80 manual."
_CANCEL = "How to cancel a transform was not stated on the manual pages read (Esc or right-click is common Blender behaviour; not verified here)."

OPERATIONS: tuple[Operation, ...] = (
    Operation(
        id="mode.enter_edit", title="Enter Edit Mode", kind="procedure",
        aliases=(("edit", "mode"), ("editmode",)),
        explanation="Edit Mode changes the shape of an object: the vertices, edges and faces of a mesh. Object Mode, the default, "
                    "works on whole objects (moving, rotating, scaling, duplicating).",
        how_to=(StepT("Make sure the object you want to edit is the active, selected object (Object Mode).",
                      (A("click", "3D Viewport", value="the object"),), start_state=(OBJ,)),
                StepT("Press Tab to enter Edit Mode.", (A("press_keys", keys=["Tab"]),), start_state=(OBJ,),
                      expected_state=(EDIT,),
                      alternatives=("Choose Edit Mode in the Mode selector in the 3D Viewport header.",))),
        clause=StepT("Enter Edit Mode", (A("press_keys", keys=["Tab"]),), start_state=(OBJ,), expected_state=(EDIT,),
                     alternatives=("Mode selector in the 3D Viewport header > Edit Mode",)),
        prerequisites=(Prereq("An object type that has an Edit Mode (such as a mesh) is the active object.", True, OBJ,
                              _editable_active, "mode.enter_object"),),
        applies_to=("MESH", "CURVE", "SURFACE", "GREASEPENCIL"), shortcuts=("tab",), menu_paths=("Mode selector > Edit Mode",),
        caveats=("Armatures use Pose Mode (Ctrl+Tab toggles it with Object Mode), not Edit Mode via Tab for posing.",
                 "The EDIT_MESH state in this app's vocabulary applies to meshes only."),
        sources=(_MODES, _XFORM, TUTORIAL), unverified=(_V280,)),
    Operation(
        id="mode.enter_object", title="Return to Object Mode", kind="procedure",
        aliases=(("object", "mode"), ("objectmode",)),
        explanation="Object Mode is Blender's default mode and works on whole objects. Press Tab again while in Edit Mode to go back to it.",
        how_to=(StepT("Press Tab to return to Object Mode.", (A("press_keys", keys=["Tab"]),), start_state=(EDIT,),
                      expected_state=(OBJ,), alternatives=("Choose Object Mode in the Mode selector in the 3D Viewport header.",)),),
        clause=StepT("Return to Object Mode", (A("press_keys", keys=["Tab"]),), start_state=(EDIT,), expected_state=(OBJ,),
                     alternatives=("Mode selector in the 3D Viewport header > Object Mode",)),
        applies_to=("MESH", "CURVE", "SURFACE", "GREASEPENCIL"), shortcuts=("tab",), menu_paths=("Mode selector > Object Mode",),
        sources=(_MODES, TUTORIAL), unverified=(_V280,)),
    Operation(
        id="mode.toggle", title="Switch between Object Mode and Edit Mode", kind="procedure",
        aliases=(("between", "object", "edit"), ("toggle", "edit"), ("toggle", "mode"), ("switch", "between", "mode"), ("tab",)),
        explanation="Tab toggles Edit Mode on an object that supports it; the Mode selector in the 3D Viewport header does the same. "
                    "What Tab does depends on the mode you are in.",
        how_to=(StepT("Press Tab to enter Edit Mode.", (A("press_keys", keys=["Tab"]),), start_state=(OBJ,), expected_state=(EDIT,),
                      alternatives=("Mode selector in the 3D Viewport header > Edit Mode",)),
                StepT("Press Tab again to return to Object Mode.", (A("press_keys", keys=["Tab"]),), start_state=(EDIT,),
                      expected_state=(OBJ,), alternatives=("Mode selector in the 3D Viewport header > Object Mode",))),
        clause=StepT("Toggle between Object Mode and Edit Mode", (A("press_keys", keys=["Tab"]),)),
        applies_to=("MESH", "CURVE", "SURFACE", "GREASEPENCIL"), shortcuts=("tab",), menu_paths=("Mode selector",),
        sources=(_MODES, TUTORIAL), unverified=(_V280,)),
    Operation(
        id="select.object", title="Select an object", kind="procedure",
        aliases=(("select", "cube"), ("select", "object"), ("select", "objects"), ("select", "sphere"), ("select", "camera"), ("select", "light")),
        explanation="In Object Mode, click an object in the 3D Viewport to select it; a selected, active object shows an orange outline.",
        how_to=(StepT("Click the object in the 3D Viewport to select it.", (A("click", "3D Viewport", value="the object"),), start_state=(OBJ,)),),
        clause=StepT("Select the object", (A("click", "3D Viewport", value="the object"),), start_state=(OBJ,)),
        shortcuts=(), sources=(_XFORM,),
        unverified=("Shift+click to add to the selection is standard Blender behaviour and visible in the tutorial video, but not confirmed on a manual page read.",)),
    Operation(
        id="select.elements", title="Select vertices, edges or faces", kind="procedure",
        aliases=(("select", "vertex"), ("select", "vertices"), ("select", "edge"), ("select", "edges"), ("select", "face"),
                 ("select", "faces"), ("select", "part")),
        explanation="In Edit Mode, choose what you select with the Vertex (1), Edge (2) and Face (3) modes, then click the elements.",
        how_to=(StepT("Enter Edit Mode (Tab) on the object.", (A("press_keys", keys=["Tab"]),), start_state=(OBJ,), expected_state=(EDIT,)),
                StepT("Choose Vertex, Edge or Face select mode with the header buttons or the 1, 2, 3 keys.",
                      (A("press_keys", keys=["1"]),), start_state=(EDIT,)),
                StepT("Click the vertices, edges or faces you want.", (A("click", "3D Viewport", value="vertices, edges or faces"),), start_state=(EDIT,))),
        clause=StepT("Select mesh elements", (A("click", "3D Viewport", value="vertices, edges or faces"),), start_state=(EDIT,)),
        prerequisites=(Prereq("The object is in Edit Mode.", True, EDIT, None, "mode.enter_edit"),),
        applies_to=("MESH",), shortcuts=("1", "2", "3"), menu_paths=(),
        caveats=("Switching select mode can change what stays selected: going up keeps only complete elements, going down keeps everything.",),
        sources=(_SELECT, TUTORIAL),
        unverified=("Shift+click to extend a selection is not stated on the manual page read (the page only describes Shift when switching modes); "
                    "it is visible in the tutorial video.", _V280)),
    Operation(
        id="transform.move", title="Move", kind="procedure",
        aliases=(("move",), ("grab",), ("translate",)),
        explanation="Press G to move the selection (in Object, Edit or Pose Mode); it follows the pointer, and a left-click confirms. "
                    "Moving an object moves its origin; moving vertices in Edit Mode leaves the origin in place.",
        how_to=(StepT("Select what you want to move.", (A("click", "3D Viewport", value="the object or elements"),)),
                StepT("Press G, move the pointer, then left-click to confirm.", (A("press_keys", keys=["G"]), A("click", "3D Viewport", value="confirm with a left-click")))),
        clause=StepT("Move the selection", (A("press_keys", keys=["G"]),)),
        prerequisites=(Prereq("Something is selected.", True, None, _selected),),
        shortcuts=("g",), menu_paths=("Object/Mesh > Transform > Move",), caveats=(_CANCEL,), sources=(_MOVE, TUTORIAL), unverified=(_CANCEL,)),
    Operation(
        id="transform.rotate", title="Rotate", kind="procedure",
        aliases=(("rotate",),),
        explanation="Press R to rotate the selection around the pivot point; press R twice for trackball rotation; X, Y or Z limits it to an axis.",
        how_to=(StepT("Select what you want to rotate.", (A("click", "3D Viewport", value="the object or elements"),)),
                StepT("Press R, move the pointer, then confirm.", (A("press_keys", keys=["R"]),))),
        clause=StepT("Rotate the selection", (A("press_keys", keys=["R"]),)),
        prerequisites=(Prereq("Something is selected.", True, None, _selected),),
        shortcuts=("r",), caveats=("The manual page read does not say how to confirm or cancel a rotation.",),
        sources=(_ROT, TUTORIAL), unverified=("How to confirm or cancel a rotation was not stated on the page read.",)),
    Operation(
        id="transform.scale", title="Scale", kind="procedure",
        aliases=(("scale",), ("resize",)),
        explanation="Press S to scale the selection: moving the pointer away from the pivot enlarges it, toward it shrinks it.",
        how_to=(StepT("Select what you want to scale.", (A("click", "3D Viewport", value="the object or elements"),)),
                StepT("Press S and move the pointer to scale.", (A("press_keys", keys=["S"]),))),
        clause=StepT("Scale the selection", (A("press_keys", keys=["S"]),)),
        prerequisites=(Prereq("Something is selected.", True, None, _selected),),
        shortcuts=("s",), caveats=("The manual page read does not describe axis keys or cancelling for scale.",),
        sources=(_SCALE,), unverified=("Axis keys and cancel for scale were not stated on the page read.",)),
    Operation(
        id="history.undo", title="Undo", kind="procedure",
        aliases=(("undo",), ("ctrl", "z")),
        explanation="Ctrl+Z undoes the last action in any mode; Edit > Undo History lists recent actions so you can jump to one. "
                    "The history is lost when Blender quits.",
        how_to=(StepT("Press Ctrl+Z to undo the last action.", (A("press_keys", keys=["Ctrl", "Z"]),),
                      alternatives=("Edit > Undo", "Edit > Undo History to jump back to a specific point")),),
        clause=StepT("Undo", (A("press_keys", keys=["Ctrl", "Z"]),), alternatives=("Edit > Undo",)),
        shortcuts=("ctrl+z",), menu_paths=("Edit > Undo", "Edit > Undo History"),
        caveats=("The manual says undo works in all modes; it describes no separate undo rules for Edit Mode.",),
        sources=(_UNDO, TUTORIAL), unverified=(_V280,)),
    Operation(
        id="history.redo", title="Redo", kind="procedure",
        aliases=(("redo",), ("shift", "ctrl", "z")),
        explanation="Shift+Ctrl+Z re-applies an action you undid (Edit > Redo).",
        how_to=(StepT("Press Shift+Ctrl+Z to redo.", (A("press_keys", keys=["Shift", "Ctrl", "Z"]),), alternatives=("Edit > Redo",)),),
        clause=StepT("Redo", (A("press_keys", keys=["Shift", "Ctrl", "Z"]),), alternatives=("Edit > Redo",)),
        shortcuts=("ctrl+shift+z",), menu_paths=("Edit > Redo",), sources=(_UNDO,)),
    Operation(
        id="object.join", title="Join objects", kind="procedure",
        aliases=(("join",), ("combine", "objects"), ("merge", "objects")),
        explanation="Join merges the selected objects into the active object, which must also be selected. All joined objects must be the same "
                    "type (mesh, curve, surface or armature).",
        how_to=(StepT("In Object Mode, select every object to join, ending with the one you want to keep, so it is the active object.",
                      (A("click", "3D Viewport", value="first object"), A("click", "3D Viewport", keys=["Shift"], value="other objects (Shift+click)")), start_state=(OBJ,)),
                StepT("Choose Object > Join, or press Ctrl+J.", (A("open_menu", "Object > Join"),), start_state=(OBJ,),
                      alternatives=("Press Ctrl+J",))),
        clause=StepT("Join the selected objects", (A("open_menu", "Object > Join"),), start_state=(OBJ,), alternatives=("Press Ctrl+J",)),
        prerequisites=(Prereq("Object Mode.", True, OBJ, None, "mode.enter_object"),
                       Prereq("Two or more objects of the same type (mesh, curve, surface or armature) are selected, and the active object is among them.",
                              True, None, _join_ok)),
        applies_to=("MESH", "CURVE", "SURFACE", "ARMATURE"), shortcuts=("ctrl+j",), menu_paths=("Object > Join",),
        caveats=("Materials, vertex groups and UV layers are merged; modifiers, constraints, groups and parent relationships are not carried over to the active object.",),
        sources=(_JOIN, TUTORIAL), unverified=(_V280,)),
    Operation(
        id="mesh.separate", title="Separate selected geometry into a new object", kind="procedure",
        aliases=(("separate",), ("split", "off")),
        explanation="Separate (Edit Mode) splits a mesh into new objects. 'Selection' moves the selected geometry into a new object; "
                    "'By Material' and 'By Loose Parts' act on the whole mesh, not just the selection.",
        how_to=(StepT("Press Tab to enter Edit Mode on the mesh.", (A("press_keys", keys=["Tab"]),), start_state=(OBJ,), expected_state=(EDIT,)),
                StepT("Select the geometry you want to move to a new object.", (A("click", "3D Viewport", value="the geometry to separate"),), start_state=(EDIT,)),
                StepT("Choose Mesh > Separate > Selection (or press P, then Selection).", (A("open_menu", "Mesh > Separate > Selection"),),
                      start_state=(EDIT,), alternatives=("Press P, then choose Selection",))),
        clause=StepT("Separate the selected geometry into a new object", (A("open_menu", "Mesh > Separate > Selection"),), start_state=(EDIT,),
                     alternatives=("Press P, then Selection",)),
        prerequisites=(Prereq("Edit Mode on a mesh.", True, EDIT, None, "mode.enter_edit"),
                       Prereq("The geometry to split off is selected (for 'Selection').", True, None, None)),
        applies_to=("MESH",), shortcuts=("p",), menu_paths=("Mesh > Separate > Selection",),
        caveats=("'By Material' and 'By Loose Parts' ignore the selection and split the whole mesh.",),
        sources=(_SEP, TUTORIAL), unverified=(_V280,)),
    Operation(
        id="mode.multi_edit", title="Edit several mesh objects at once", kind="procedure",
        aliases=(("edit", "multiple"), ("multiple", "objects"), ("several", "objects"), ("edit", "two", "objects"), ("edit", "both")),
        explanation="Edit Mode can work on several objects together: select all of them in Object Mode, then press Tab. "
                    "Vertices of different objects cannot be connected while they stay separate objects.",
        how_to=(StepT("In Object Mode select all the mesh objects you want to edit (Shift+click to add).",
                      (A("click", "3D Viewport", value="first object"), A("click", "3D Viewport", keys=["Shift"], value="other objects (Shift+click)")), start_state=(OBJ,)),
                StepT("Press Tab to enter Edit Mode for all of them.", (A("press_keys", keys=["Tab"]),), start_state=(OBJ,), expected_state=(EDIT,))),
        clause=StepT("Select several objects and enter Edit Mode", (A("press_keys", keys=["Tab"]),), start_state=(OBJ,), expected_state=(EDIT,)),
        applies_to=("MESH",), shortcuts=("tab",),
        caveats=("The Properties editor shows only the active object; selecting an element makes its object active.",
                 "Connecting vertices across different objects does not work."),
        sources=(_MODES, TUTORIAL), unverified=(_V280,)),
    Operation(
        id="trouble.cross_object_connect", title="Why vertices of two objects cannot be connected", kind="troubleshooting",
        aliases=(), triggers=(("connect", "vertices", "objects"), ("connect", "vertices", "different"), ("connect", "vertices", "two"),
                              ("fill", "two", "objects"), ("join", "vertices", "objects"), ("connect", "two", "objects")),
        explanation="Edit Mode can edit several objects at once, but vertices that belong to different objects cannot be connected. "
                    "Join the objects into one first (Object Mode, Object > Join or Ctrl+J), then connect the vertices.",
        how_to=(), clause=None, remedy_op="object.join", applies_to=("MESH",),
        sources=(_MODES, _JOIN, TUTORIAL), unverified=(_V280,)),
)

# Which existing caveats are PITFALLS (the rest are documentation gaps or notes about this app's vocabulary and must not be presented as user mistakes).
# Exact strings, so editing a caveat without revisiting this table fails tests/test_service.py::test_every_pitfall_is_a_real_caveat.
PITFALLS: dict[str, tuple[str, ...]] = {
    "mode.enter_edit": ("Armatures use Pose Mode (Ctrl+Tab toggles it with Object Mode), not Edit Mode via Tab for posing.",),
    "select.elements": ("Switching select mode can change what stays selected: going up keeps only complete elements, going down keeps everything.",),
    "object.join": ("Materials, vertex groups and UV layers are merged; modifiers, constraints, groups and parent relationships are not carried over to the active object.",),
    "mesh.separate": ("'By Material' and 'By Loose Parts' ignore the selection and split the whole mesh.",),
    "mode.multi_edit": ("The Properties editor shows only the active object; selecting an element makes its object active.", "Connecting vertices across different objects does not work."),
}
OPERATIONS = tuple(replace(o, pitfalls=PITFALLS[o.id]) if o.id in PITFALLS else o for o in OPERATIONS)
BY_ID = {o.id: o for o in OPERATIONS}
assert len(BY_ID) == len(OPERATIONS)

# Words that name Blender topics this catalog does NOT cover. If a request is only about these, nothing here can answer it.
UNSUPPORTED_TERMS = frozenset({
    "bevel", "extrude", "inset", "loop", "subdivide", "subdivision", "sculpt", "sculpting", "render", "rendering", "modifier",
    "modifiers", "uv", "unwrap", "texture", "textures", "shader", "shaders", "animation", "animate", "keyframe", "keyframes",
    "lighting", "rig", "rigging", "particles", "physics", "cycles", "eevee", "nodes", "boolean",
    "mirror", "array", "decimate", "retopology", "paint", "compositing", "python", "script", "addon", "export", "import",
})


PHRASE_OPS = frozenset({"mode.enter_edit", "mode.enter_object"})


def tokens(text: str) -> set[str]:
    """Lowercase words plus a crude stem of each (connecting -> connect, objects -> object)."""
    out = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        out.add(w)
        if len(w) > 4:
            for suf in ("ing", "es", "s"):
                if w.endswith(suf) and len(w) - len(suf) >= 3:
                    out.add(w[: -len(suf)])   # every applicable stem: 'cubes' -> 'cub' and 'cube'
    return out


def match_aliases(text: str, kinds: tuple[str, ...] = ("procedure",)) -> list[tuple[Operation, int]]:
    """Operations whose alias group is contained in the text's words, best specificity first. Specificity =
    number of words in the matching group (longer group = more specific)."""
    toks = tokens(text)
    joined = " " + " ".join(re.findall(r"[a-z0-9]+", text.lower())) + " "
    out = []
    for op in OPERATIONS:
        if op.kind not in kinds:
            continue
        # 'edit mode' / 'object mode' must be an actual phrase: as loose words, "Edit Mode ... the object" would match 'object mode'
        ok = (lambda g: f" {' '.join(g)} " in joined) if op.id in PHRASE_OPS else (lambda g: set(g) <= toks)
        best = max((len(g) for g in op.aliases if ok(g)), default=0)
        if best:
            out.append((op, best))
    return sorted(out, key=lambda t: (-t[1], t[0].id))


def match_troubleshooting(text: str) -> list[Operation]:
    toks = tokens(text)
    return [op for op in OPERATIONS if op.kind == "troubleshooting" and any(set(g) <= toks for g in op.triggers)]


def parse_version(v: str | None) -> tuple[int, int] | None:
    m = re.match(r"^\s*(\d+)\.(\d+)", v or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def version_status(op: Operation, version: str | None) -> tuple[str, str]:
    """('incompatible' | 'unverified' | 'unknown', note). Never 'verified' for a version whose manual was not read:
    only the current manual (main) was read."""
    pv = parse_version(version)
    if pv is None:
        return "unknown", "Blender version not provided: the procedure is documented for the current manual only; please confirm your version."
    if pv < op.min_version:
        return "incompatible", f"'{op.title}' needs Blender {op.min_version[0]}.{op.min_version[1]} or newer."
    return "unverified", (f"Documented from the current manual (main); Blender {version} itself was not checked against its own manual. "
                          "Shortcuts and menu names for this operation are long-standing but verify on your version.")


def normalise_shortcut(text: str) -> str:
    t = text.lower().replace(" ", "")
    t = re.sub(r"(control|ctl)", "ctrl", t)
    t = t.replace("-", "+")
    parts = [p for p in t.split("+") if p]
    mods = sorted((p for p in parts if p in ("ctrl", "shift", "alt")), key=lambda p: ("ctrl", "shift", "alt").index(p))
    keys = [p for p in parts if p not in ("ctrl", "shift", "alt")]
    return "+".join(mods + keys)
