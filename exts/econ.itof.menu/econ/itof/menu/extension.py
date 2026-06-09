"""Adds the e-con DepthVista Helix iToF cameras to Isaac Sim's Create menu.

Uses the stable ``omni.kit.menu.utils.MenuItemDescription`` API. Kit menus merge by
name, so our ``e-con`` vendor joins the existing
``Create > Sensors > Camera and Depth Sensors`` path next to Intel/Stereolabs. Each leaf
references the matching USD into the stage.
"""

import gc
import os

import carb
import omni.ext
import omni.kit.app
import omni.usd
from omni.kit.menu.utils import MenuItemDescription, add_menu_items, remove_menu_items

VENDOR = "e-con"
CAMERAS = [
    {"name": "DepthVista Helix iToF (USB)",  "usd": "DEPTH_VISTA_HELIX_USB.usd",  "prim": "/DEPTH_VISTA_HELIX_USB"},
    {"name": "DepthVista Helix iToF (GMSL)", "usd": "DEPTH_VISTA_HELIX_GMSL.usd", "prim": "/DEPTH_VISTA_HELIX_GMSL"},
]


def _sensor_glyph():
    """Path to the stock 'Sensors' menu icon, so our merged item keeps the glyph."""
    try:
        mgr = omni.kit.app.get_app().get_extension_manager()
        for e in mgr.get_extensions():
            if e.get("name", "").startswith("isaacsim.sensors.camera.ui"):
                g = os.path.join(mgr.get_extension_path(e["id"]), "data", "sensor.svg")
                return g if os.path.isfile(g) else None
    except Exception:
        pass
    return None


class Extension(omni.ext.IExt):
    def on_startup(self, ext_id: str):
        self._asset_dir = os.path.join(
            omni.kit.app.get_app().get_extension_manager().get_extension_path(ext_id), "assets")

        leaves = [
            MenuItemDescription(
                name=cam["name"],
                onclick_fn=lambda up=os.path.join(self._asset_dir, cam["usd"]),
                                  pp=cam["prim"]: self._add_camera(up, pp),
            )
            for cam in CAMERAS
        ]

        # Nested by name so add_menu_items merges into the existing menu path.
        self._menu_items = [
            MenuItemDescription(name="Sensors", glyph=_sensor_glyph(), sub_menu=[
                MenuItemDescription(name="Camera and Depth Sensors", sub_menu=[
                    MenuItemDescription(name=VENDOR, sub_menu=leaves),
                ]),
            ]),
        ]
        add_menu_items(self._menu_items, "Create")

    def on_shutdown(self):
        if getattr(self, "_menu_items", None):
            remove_menu_items(self._menu_items, "Create")
            self._menu_items = None
        gc.collect()

    def _add_camera(self, usd_path: str, prim_prefix: str):
        """Reference the asset at the next free prim path and select it."""
        if not os.path.isfile(usd_path):
            carb.log_error(f"[econ.itof.menu] asset not found: {usd_path}")
            return
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return
        prim_path = self._next_free_path(stage, prim_prefix)
        try:
            stage.DefinePrim(prim_path, "Xform").GetReferences().AddReference(
                usd_path.replace(os.sep, "/"))
            omni.usd.get_context().get_selection().set_selected_prim_paths([prim_path], True)
        except Exception as exc:  # never let a click crash the menu
            carb.log_error(f"[econ.itof.menu] failed to add {usd_path}: {exc}")

    @staticmethod
    def _next_free_path(stage, base: str) -> str:
        if not stage.GetPrimAtPath(base).IsValid():
            return base
        i = 1
        while stage.GetPrimAtPath(f"{base}_{i:02d}").IsValid():
            i += 1
        return f"{base}_{i:02d}"
