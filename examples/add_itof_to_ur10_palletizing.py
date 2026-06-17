#!/usr/bin/env python3
"""Add two e-con DepthVista Helix iToF cameras to the UR10 Palletizing example.

Run this from the Isaac Sim Script Editor.  First load the example scene:

    Window -> Robotics Examples -> (Manipulation) UR10 Palletizing  ->  Load

then run this file.  It references the same DepthVista Helix iToF USD that the
Create menu uses, and places two units:

  1. /World/Ur10Table/ur10/ee_link/DEPTHVISTA_HELIX   (wrist, eye-in-hand)
         translate (0.07, -0.055, 0.0)   rotateXYZ (90, 90, 0)
  2. /World/Ur10Table/pallet/DEPTHVISTA_HELIX          (over the pallet, eye-to-hand)
         translate (0.0, 0.0, 1.5)       rotateXYZ (-90, 0, 0)

Translations are in stage units (metres in the example).  As with the menu, a
units-compensating scale (asset mm -> stage m) is applied so the camera is its
true ~95 mm size.  Re-running replaces the cameras, so it is idempotent.
"""

import os

import omni.usd
import omni.kit.app
from pxr import Usd, UsdGeom, Gf

EXT_NAME  = "econ.itof.menu"
ASSET_USD = "DEPTHVISTA_HELIX_GMSL.usd"

CAMERAS = [
    {
        "path": "/World/Ur10Table/ur10/ee_link/DEPTHVISTA_HELIX",
        "translate": (0.07, -0.055, 0.0),
        "rotate":    (90.0, 90.0, 0.0),
    },
    {
        "path": "/World/Ur10Table/pallet/DEPTHVISTA_HELIX",
        "translate": (0.0, 0.0, 1.5),
        "rotate":    (-90.0, 0.0, 0.0),
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


def _add_camera(stage, spec: dict, asset_path: str, scale: float):
    """Reference the camera at spec['path'] and author its T/R/S transform."""
    path = spec["path"]
    parent = path.rsplit("/", 1)[0]
    if not stage.GetPrimAtPath(parent).IsValid():
        print(f"[econ] parent prim missing: {parent}")
        print("       Load 'UR10 Palletizing' first "
              "(Window -> Robotics Examples -> ... -> Load), then re-run.")
        return False

    if stage.GetPrimAtPath(path).IsValid():       # idempotent re-run
        stage.RemovePrim(path)

    prim = stage.DefinePrim(path, "Xform")
    prim.GetReferences().AddReference(asset_path)

    # Author a clean local T * R * S (overrides any transform from the reference).
    xform = UsdGeom.Xformable(prim)
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(Gf.Vec3d(*spec["translate"]))
    xform.AddRotateXYZOp().Set(Gf.Vec3f(*spec["rotate"]))
    if abs(scale - 1.0) > 1e-9:
        xform.AddScaleOp().Set(Gf.Vec3f(scale, scale, scale))

    print(f"[econ] added {path}  t={spec['translate']}  r={spec['rotate']}  scale={scale}")
    return True


def main():
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        print("[econ] No stage open.")
        return

    asset = _find_asset()
    if not asset:
        print(f"[econ] Could not find {ASSET_USD} via the '{EXT_NAME}' extension.")
        print("       Install the extension first (build.sh / build.bat).")
        return

    scale = _unit_scale(stage, asset)
    added = [s["path"] for s in CAMERAS if _add_camera(stage, s, asset, scale)]
    if added:
        omni.usd.get_context().get_selection().set_selected_prim_paths(added, True)
    print(f"[econ] done — {len(added)}/{len(CAMERAS)} camera(s) added.")


main()
