"""Per-application profiles: the closed vocabulary extraction is allowed to use.

NOTE (unverified): the Blender lists below were written from knowledge of Blender 4.x and
have NOT yet been checked against the pinned Blender version. They must be regenerated
from a real Blender install (bpy) once the team fixes the version; until then unknown
names produce warnings, never hard failures.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


def norm(s: str) -> str:
    """Normalise a UI label for comparison."""
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


@dataclass(frozen=True)
class AppProfile:
    name: str
    modes: frozenset[str]
    tools: frozenset[str]
    workspaces: frozenset[str]
    selection_types: frozenset[str]
    ui_names: frozenset[str] = field(default_factory=frozenset)  # normalised labels
    panels: frozenset[str] = field(default_factory=frozenset)
    nodes: frozenset[str] = field(default_factory=frozenset)  # node/object types a node_exists predicate may name (Maya, Houdini)
    mode_aliases: dict[str, str] = field(default_factory=dict)  # upper_snake alias -> canonical mode

    def has_ui_name(self, label: str) -> bool:
        return norm(label) in self.ui_names


_BLENDER_UI = """
File;Edit;Render;Window;Help;Add;Select;Object;Mesh;Curve;View;Mode;Edit Mode;Object Mode;Sculpt Mode;
Pose Mode;Vertex Paint;Weight Paint;Texture Paint;Cube;Plane;Circle;Grid;UV Sphere;Ico Sphere;Cylinder;
Cone;Torus;Monkey;Empty;Camera;Light;Point;Sun;Spot;Area;Armature;Text;Move;Rotate;Scale;Transform;
Select Box;Tweak;Annotate;Measure;Extrude;Extrude Region;Inset Faces;Bevel;Loop Cut;Offset Edge Slide;
Knife;Poly Build;Spin;Smooth;Shrink Fatten;Push Pull;Draw;Clay Strips;Grab;Inflate;Mask;
Add Modifier;Modifiers;Subdivision Surface;Mirror;Array;Boolean;Solidify;Bevel Modifier;Decimate;
Modifier Properties;Material Properties;Object Properties;Object Data Properties;Render Properties;
Output Properties;World Properties;Physics Properties;Particle Properties;Constraints;
3D Viewport;Properties;Outliner;Timeline;Shader Editor;Geometry Node Editor;UV Editor;Image Editor;
Compositor;Dope Sheet;Graph Editor;Video Sequencer;Text Editor;Spreadsheet;
Layout;Modeling;Sculpting;UV Editing;Texture Paint;Shading;Animation;Rendering;Compositing;
Geometry Nodes;Scripting;Viewport Shading;Wireframe;Solid;Material Preview;Rendered;
Shade Smooth;Shade Flat;Apply;Duplicate Objects;Delete;Join;Separate;Parent;Origin to Geometry;
Set Origin;Snap;Proportional Editing;Pivot Point;Transform Orientation;Cursor;3D Cursor;
Vertex Select;Edge Select;Face Select;Principled BSDF;Image Texture;Base Color;Roughness;Metallic;
Emission;Color Ramp;Render Engine;Eevee;Cycles;Workbench;Samples;Resolution;Frame Rate;
Keyframe;Insert Keyframe;Play;Frame Start;Frame End;Render Image;Render Animation;
Collection;New Collection;Link;Unlink;Hide;Unhide;Select All;Deselect All;Invert Selection;
Select Linked;Merge;Merge Vertices;Fill;Grid Fill;Bridge Edge Loops;Dissolve;Subdivide;Triangulate;
Separate;Selection;By Material;By Loose Parts;Duplicate;Mirror Vertices;Recalculate Normals;Flip Normals;
Mode Selector;Undo;Redo;Undo History;Repeat History;Adjust Last Operation;Pose Mode;Make Edge Face;New Edge Face from Vertices;Rip;Vertices;Edges;Faces;Face;Edge;Vertex;Loop Select;Ring Select;
Select Random;Checker Deselect;Select More;Select Less;Grow Selection;Shrink Selection;Similar;
Origin;Set Origin Geometry to Origin;Clear Parent;Make Parent;Apply Transformations;All Transforms;
Location;Rotation;Scale Transform;Convert;Copy;Paste;Undo;Redo;Preferences;Save;Open;New;Append;Import;Export;
Objects;Add Object;Quick Effects;Rigid Body;Clean Up;Delete Loose;Limited Dissolve;Weights;Normals;
UV;Unwrap;Smart UV Project;Mark Seam;Clear Seam;Pin;Mirror Modifier;Subsurf;Level Viewport;Render Levels;
Vertex Groups;Shape Keys;Data;Add Material;New Material;Assign;Slot;Shader;Node;Add Node;
Sidebar;Toolbar;N Panel;T Panel;Tool Settings;Header;Status Bar;Gizmo;Overlays;Statistics;
Snapping;Magnet;Axis;X Axis;Y Axis;Z Axis;Global;Local;Normal;Gimbal;View Selected;Frame Selected;
Orthographic;Perspective;Front;Back;Right;Left;Top;Bottom;Camera View;Local View;Isolate;X-Ray;Toggle X-Ray;
Fly;Walk;Navigation Gizmo;Numpad;Mouse Wheel;Middle Mouse Button;MMB;LMB;RMB;Scroll;Shift;Ctrl;Alt;Tab;Delete Key
"""

BLENDER = AppProfile(
    name="blender",
    modes=frozenset({
        "OBJECT", "EDIT_MESH", "EDIT_CURVE", "EDIT_ARMATURE", "SCULPT", "POSE",
        "PAINT_VERTEX", "PAINT_WEIGHT", "PAINT_TEXTURE",
    }),
    tools=frozenset({
        "builtin.select_box", "builtin.select", "builtin.select_circle", "builtin.select_lasso",
        "builtin.cursor", "builtin.move", "builtin.rotate", "builtin.scale", "builtin.transform",
        "builtin.annotate", "builtin.measure", "builtin.extrude_region", "builtin.inset_faces",
        "builtin.bevel", "builtin.loop_cut", "builtin.offset_edge_slide", "builtin.knife",
        "builtin.poly_build", "builtin.spin", "builtin.smooth", "builtin.shrink_fatten",
        "builtin.push_pull", "builtin_brush.Draw", "builtin_brush.Clay Strips",
        "builtin_brush.Grab", "builtin_brush.Inflate", "builtin_brush.Mask",
    }),
    workspaces=frozenset({
        "Layout", "Modeling", "Sculpting", "UV Editing", "Texture Paint", "Shading",
        "Animation", "Rendering", "Compositing", "Geometry Nodes", "Scripting",
    }),
    selection_types=frozenset({
        "NONE", "MESH", "CURVE", "LIGHT", "CAMERA", "EMPTY", "ARMATURE", "VERTEX", "EDGE", "FACE",
    }),
    ui_names=frozenset(norm(n) for n in _BLENDER_UI.replace("\n", "").split(";") if n.strip()),
    mode_aliases={
        "EDIT_MODE": "EDIT_MESH", "EDIT": "EDIT_MESH", "OBJECT_MODE": "OBJECT",
        "SCULPT_MODE": "SCULPT", "POSE_MODE": "POSE", "VERTEX_PAINT": "PAINT_VERTEX",
        "WEIGHT_PAINT": "PAINT_WEIGHT", "TEXTURE_PAINT": "PAINT_TEXTURE",
    },
    panels=frozenset({
        "Properties:Modifiers", "Properties:Material", "Properties:Object", "Properties:Render",
        "Properties:Output", "Properties:World", "Properties:Physics", "Properties:Data",
        "Outliner", "Timeline", "Shader Editor", "UV Editor", "Sidebar", "Toolbar",
    }),
)

# MAYA and HOUDINI: written from the feature matrix (knowledge/rigging_features.json) and recalled knowledge, NOT checked against an install.
# Unknown names produce warnings, never failures (same policy as Blender). Houdini is node-based, so its checkable state is mostly
# "this node exists" (node_exists), not a mode; Maya mixes both.
_MAYA_UI = """
File;Edit;Create;Select;Modify;Display;Windows;Skeleton;Skin;Constrain;Control;Deform;Animation;Rigging;Modeling;Rendering;FX;
Create Joints;Insert Joint;Remove Joint;Reroot Skeleton;Mirror Joint;Orient Joint;Create IK Handle;IK Spline Handle;Set Preferred Angle;
Bind Skin;Detach Skin;Paint Skin Weights;Mirror Skin Weights;Copy Skin Weights;Prune Small Weights;Normalize Weights;Component Editor;
Parent Constraint;Point Constraint;Orient Constraint;Scale Constraint;Aim Constraint;Pole Vector Constraint;Channel Box;Attribute Editor;
Outliner;Hypergraph;Node Editor;Graph Editor;Dope Sheet;Time Editor;Time Slider;Range Slider;Animation Layer Editor;Trax Editor;
Set Key;Auto Key;Key Selected;Bake Simulation;Euler Filter;Simplify Curve;Motion Trail;Ghost Selected;Playblast;HumanIK;Characterize;Retarget;
Quick Rig;Blend Shape;Shape Editor;Delta Mush;Lattice;Cluster;Wrap;Jiggle;Freeze Transformations;Delete by Type;History;Group;Locator;NURBS Circle;
Parent;Maintain Offset;Add Attribute;Attribute Name;Minimum;Maximum;Search For;Replace With;Search and Replace Names;Type;Primary Axis;Secondary Axis;Orient Joint Options;Connection Editor;Reverse;Move;Rotate;Scale;
Quick Select Sets;Display Layers;Move Tool;Rotate Tool;Scale Tool;Select Tool;Lasso Tool;Game Exporter;Send to Unreal;FBX Export;Alembic Cache;
"""

_HOUDINI_UI = """
File;Edit;Render;Windows;Help;Build;Animate;Rigging;Network View;Scene View;Parameters;Geometry Spreadsheet;Animation Editor;Take List;
Skeleton;Edit Skeleton;Rig Doctor;Orient Joints;Skeleton Mirror;Rig Pose;Rig Stash Pose;Rig Match Pose;Rig Vellum;IK Chains;Full Body IK;
Bone Deform;Joint Deform;Bone Capture Proximity;Joint Capture Biharmonic;Capture Layer Paint;Capture Mirror;Delta Mush;Map Points;
Biped Retarget;Animation from Skeleton;FBX Character Import;FBX Animation Import;Mocap Import;Mocap Stream;FBX Character Output;FBX Animation Output;
GLTF Character Output;Character Blend Shapes;Configure Controls;Character Picker;Autorig Builder;APEX;Motion Mixer;Motion Clips;Animation Catalog;
Transform Driver;Look At;Secondary Motion;Ragdoll;Rest Twist;IK FK Blend;Bake;Retime;Flipbook;Pack Folder;Character Pack;Object Merge;Null;Transform;
Set Key;Auto Key;Keyframe;Graph Debugger;
"""

MAYA = AppProfile(
    name="maya",
    modes=frozenset({"OBJECT", "COMPONENT", "VERTEX", "EDGE", "FACE", "JOINT", "ANIMATION", "RIGGING", "MODELING"}),
    tools=frozenset({"Move Tool", "Rotate Tool", "Scale Tool", "Select Tool", "Lasso Tool", "Paint Skin Weights Tool", "Create Joints Tool",
                     "Insert Joint Tool", "IK Handle Tool", "Soft Modification Tool", "Sculpt Geometry Tool"}),
    workspaces=frozenset({"Modeling", "Sculpting", "Rigging", "Animation", "Rendering", "FX", "Motion Graphics", "Time Editor", "Graph Editor"}),
    selection_types=frozenset({"NONE", "MESH", "JOINT", "CURVE", "LIGHT", "CAMERA", "LOCATOR", "IK_HANDLE", "CONTROL", "VERTEX", "EDGE", "FACE"}),
    ui_names=frozenset(norm(n) for n in _MAYA_UI.replace("\n", "").split(";") if n.strip()),
    mode_aliases={"OBJECT_MODE": "OBJECT", "COMPONENT_MODE": "COMPONENT", "ANIMATION_MENU_SET": "ANIMATION", "RIGGING_MENU_SET": "RIGGING"},
    panels=frozenset({"Channel Box", "Attribute Editor", "Outliner", "Graph Editor", "Dope Sheet", "Time Editor", "Node Editor", "Hypergraph",
                      "Component Editor", "Animation Layer Editor", "HumanIK"}),
    nodes=frozenset({"joint", "ikHandle", "ikEffector", "skinCluster", "blendShape", "parentConstraint", "pointConstraint", "orientConstraint",
                     "scaleConstraint", "aimConstraint", "poleVectorConstraint", "animLayer", "nurbsCurve", "locator", "deltaMush", "lattice",
                     "jiggle", "motionTrail", "HIKCharacterNode"}),
)

HOUDINI = AppProfile(
    name="houdini",
    modes=frozenset({"SELECT", "EDIT_SKELETON", "ANIMATE", "HANDLE"}),
    tools=frozenset({"Select", "Edit Skeleton", "Rig Pose", "Animate", "Handle", "Translate", "Rotate", "Scale"}),
    workspaces=frozenset({"Build", "Animate", "Rigging", "Tech", "Solaris"}),
    selection_types=frozenset({"NONE", "POINT", "PRIMITIVE", "JOINT", "NODE", "CONTROL"}),
    ui_names=frozenset(norm(n) for n in _HOUDINI_UI.replace("\n", "").split(";") if n.strip()),
    mode_aliases={"EDIT SKELETON": "EDIT_SKELETON", "ANIMATE_STATE": "ANIMATE"},
    panels=frozenset({"Network View", "Scene View", "Parameters", "Geometry Spreadsheet", "Animation Editor", "Take List", "Graph Debugger"}),
    nodes=frozenset({"Skeleton", "Rig Doctor", "Orient Joints", "Skeleton Mirror", "Rig Pose", "Rig Stash Pose", "Rig Match Pose", "IK Chains",
                     "Full Body IK", "Bone Deform", "Joint Deform", "Bone Capture Proximity", "Joint Capture Biharmonic", "Capture Layer Paint",
                     "Capture Mirror", "Map Points", "Biped Retarget", "Animation from Skeleton", "FBX Character Import", "FBX Animation Import",
                     "Mocap Import", "Mocap Stream", "FBX Character Output", "FBX Animation Output", "GLTF Character Output",
                     "Character Blend Shapes", "Configure Controls", "Motion Mixer", "Motion Clips", "Delta Mush", "Look At", "Secondary Motion",
                     "Ragdoll", "Pack Folder", "Character Pack", "Object Merge", "Null", "Transform"}),
)

PROFILES: dict[str, AppProfile] = {"blender": BLENDER, "maya": MAYA, "houdini": HOUDINI}


def get_profile(app: str) -> AppProfile:
    try:
        return PROFILES[app]
    except KeyError:
        raise ValueError(
            f"No profile for app '{app}'. Supported: {sorted(PROFILES)}. "
            "Other applications are out of scope."
        ) from None


def load_overlay(profile: AppProfile, json_path: str) -> AppProfile:
    """Return a profile extended with names from scripts/dump_blender_vocab.py output.
    Only adds; never removes built-in entries."""
    import json

    d = json.load(open(json_path, encoding="utf-8"))
    return AppProfile(
        name=profile.name,
        modes=profile.modes | frozenset(d.get("modes", [])),
        tools=profile.tools,
        workspaces=profile.workspaces | frozenset(d.get("workspaces", [])),
        selection_types=profile.selection_types,
        ui_names=profile.ui_names | frozenset(norm(n) for n in d.get("ui_names", [])),
        panels=profile.panels,
        mode_aliases=profile.mode_aliases,
    )
