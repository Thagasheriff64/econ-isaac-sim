#!/usr/bin/env python3
"""Add e-con DepthVista Helix iToF cameras (and a floating-camera stand) to the
UR10 Palletizing example.

Run this from the Isaac Sim Script Editor.  First load the example scene:

    Window -> Robotics Examples -> (Manipulation) UR10 Palletizing  ->  Load

then run this file.  It runs in two steps:

  1. Cameras — reference the same DepthVista Helix iToF USD the Create menu uses:
       /World/Ur10Table/ur10/ee_link/DEPTHVISTA_HELIX   (wrist, eye-in-hand)
           translate (0.07, 0.055, 0.0)    rotateXYZ (90, 90, 0)
       /World/Ur10Table/pallet/DEPTHVISTA_HELIX          (over the pallet, eye-to-hand)
           translate (0.0, 0.0, 1.5)        rotateXYZ (-90, 0, 0)

  2. Floating-camera stand — a referenced Isaac Stand prop plus a cylinder arm:
       /World/Ur10Table/dolly/Stand     (referenced stand_instanceable.usd)
           translate (1.2, 0.0, 1.88193) rotateXYZ (0, 0, 0)  scale (1.2, 1.2, 3.66786)
       /World/Ur10Table/dolly/Cylinder  (Create > Mesh > Cylinder)
           translate (0.6, 0.0, 1.88)    rotateXYZ (0, 90, 0) scale (0.0282, 0.07185, 1.3)

Translations are in stage units (metres in the example).  For the cameras a
units-compensating scale (asset mm -> stage m) is applied so they are their true
~95 mm size.  Re-running replaces what it creates, so it is idempotent.
"""

import os

import omni.usd
import omni.kit.app
from pxr import Usd, UsdGeom, Gf

EXT_NAME    = "econ.itof.menu"
ASSET_USD   = "DEPTHVISTA_HELIX_GMSL.usd"
EXAMPLE_ROOT = "/World/Ur10Table"     # created by the UR10 Palletizing example

STAND_USD = ("https://omniverse-content-production.s3-us-west-2.amazonaws.com"
             "/Assets/Isaac/5.1/Isaac/Props/Mounts/Stand/stand_instanceable.usd")

CAMERAS = [
    {
        "path": "/World/Ur10Table/ur10/ee_link/DEPTHVISTA_HELIX",
        "translate": (0.07, 0.055, 0.0),
        "rotate":    (90.0, 90.0, 0.0),
    },
    {
        "path": "/World/Ur10Table/pallet/DEPTHVISTA_HELIX",
        "translate": (0.0, 0.0, 1.5),
        "rotate":    (-90.0, 0.0, 0.0),
    },
]

# Floating-camera stand, added second.  "reference" pulls in a USD asset;
# "cylinder" creates a mesh cylinder (Create > Mesh > Cylinder).
PROPS = [
    {
        "kind": "reference", "usd": STAND_USD,
        "path": "/World/Ur10Table/dolly/Stand",
        "translate": (1.2, 0.0, 1.88193),
        "rotate":    (0.0, 0.0, 0.0),
        "scale":     (1.2, 1.2, 3.66786),
    },
    {
        "kind": "cylinder",
        "path": "/World/Ur10Table/dolly/Cylinder",
        "translate": (0.6, 0.0, 1.88),
        "rotate":    (0.0, 90.0, 0.0),
        "scale":     (0.0282, 0.07185, 1.3),
    },
]


def _find_asset() -> "str | None":
    """Locate the DepthVista USD inside the installed econ.itof.menu extension."""
    mgr = omni.kit.app.get_app().get_extension_manager()
    for ext in mgr.get_extensions():
        if ext.get("name") == EXT_NAME:
            path = os.path.join(mgr.get_extension_path(ext["id"]), "assets", ASSET_USD)
            if os.path.isfile(path):
                return path.replace(os.sep, "/")
    return None


def _unit_scale(stage, asset_path: str) -> float:
    """asset metersPerUnit / stage metersPerUnit (0.001 for a mm asset in a m stage)."""
    stage_mpu = UsdGeom.GetStageMetersPerUnit(stage) or 1.0
    asset_mpu = UsdGeom.GetStageMetersPerUnit(Usd.Stage.Open(asset_path)) or 1.0
    return asset_mpu / stage_mpu


def _set_trs(prim, translate, rotate, scale):
    """Author a clean local T * R * S on prim (overrides any existing transform)."""
    xform = UsdGeom.Xformable(prim)
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(Gf.Vec3d(*translate))
    xform.AddRotateXYZOp().Set(Gf.Vec3f(*rotate))
    xform.AddScaleOp().Set(Gf.Vec3f(*scale))


def _example_loaded(stage) -> bool:
    if stage.GetPrimAtPath(EXAMPLE_ROOT).IsValid():
        return True
    print(f"[econ] {EXAMPLE_ROOT} missing — load 'UR10 Palletizing' first "
          "(Window -> Robotics Examples -> ... -> Load), then re-run.")
    return False


def _add_camera(stage, spec: dict, asset_path: str, scale: float) -> bool:
    """Reference the camera at spec['path'] and author its transform."""
    path = spec["path"]
    if not stage.GetPrimAtPath(path.rsplit("/", 1)[0]).IsValid():
        print(f"[econ] parent prim missing for {path}")
        return False
    if stage.GetPrimAtPath(path).IsValid():        # idempotent re-run
        stage.RemovePrim(path)
    prim = stage.DefinePrim(path, "Xform")
    prim.GetReferences().AddReference(asset_path)
    _set_trs(prim, spec["translate"], spec["rotate"], (scale, scale, scale))
    print(f"[econ] camera {path}  t={spec['translate']}  r={spec['rotate']}")
    return True


def _create_mesh_cylinder(stage, path: str):
    """Create a cylinder via the Create > Mesh > Cylinder command so its base size
    matches the GUI; fall back to an analytic UsdGeom.Cylinder if unavailable."""
    try:
        import omni.kit.commands
        omni.kit.commands.execute("CreateMeshPrimWithDefaultXform",
                                  prim_type="Cylinder", prim_path=path,
                                  select_new_prim=False)
        prim = stage.GetPrimAtPath(path)
        if prim and prim.IsValid():
            return prim
    except Exception as exc:
        print(f"[econ] mesh-cylinder command failed ({exc}); using analytic cylinder")
    return UsdGeom.Cylinder.Define(stage, path).GetPrim()


def _add_prop(stage, spec: dict) -> bool:
    """Add a referenced asset or a mesh cylinder under /World/Ur10Table/dolly."""
    path = spec["path"]
    stage.DefinePrim(path.rsplit("/", 1)[0], "Xform")   # ensure the dolly group
    if stage.GetPrimAtPath(path).IsValid():             # idempotent re-run
        stage.RemovePrim(path)

    if spec["kind"] == "reference":
        prim = stage.DefinePrim(path, "Xform")
        prim.GetReferences().AddReference(spec["usd"])
    else:
        prim = _create_mesh_cylinder(stage, path)

    if not (prim and prim.IsValid()):
        print(f"[econ] failed to create {path}")
        return False
    _set_trs(prim, spec["translate"], spec["rotate"], spec["scale"])
    print(f"[econ] prop   {path}  t={spec['translate']}  r={spec['rotate']}  s={spec['scale']}")
    return True


def main():
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        print("[econ] No stage open.")
        return
    if not _example_loaded(stage):
        return

    asset = _find_asset()
    if not asset:
        print(f"[econ] Could not find {ASSET_USD} via the '{EXT_NAME}' extension.")
        print("       Install the extension first (build.sh / build.bat).")
        return
    scale = _unit_scale(stage, asset)

    # Step 1 — cameras
    added = [s["path"] for s in CAMERAS if _add_camera(stage, s, asset, scale)]
    # Step 2 — floating-camera stand
    added += [s["path"] for s in PROPS if _add_prop(stage, s)]

    if added:
        omni.usd.get_context().get_selection().set_selected_prim_paths(added, True)
    print(f"[econ] done — {len(added)} prim(s) added "
          f"({len(CAMERAS)} cameras + {len(PROPS)} stand parts).")


main()
