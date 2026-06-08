"""Adds e-con DepthVista Helix iToF cameras to the Isaac Sim Create menu.

Builds the submenu with the stable ``omni.kit.menu.utils.MenuItemDescription`` +
``add_menu_items`` API (the long-standing Kit menu mechanism). Because Kit menus merge
by name, our ``e-con`` vendor appears under the existing
``Create > Sensors > Camera and Depth Sensors`` path, alongside Intel/Orbbec/Stereolabs.

Each leaf's click handler adds the matching reference USD to the stage. The dropped prim
(``DEPTH_VISTA_HELIX_USB`` / ``_GMSL``) is exactly what ``isaac_usd_ros_itof.py`` discovers
for ROS 2 streaming.
"""

import gc
import os

import carb
import omni.ext
import omni.kit.app
import omni.usd

from omni.kit.menu.utils import MenuItemDescription, add_menu_items, remove_menu_items


# Vendor + leaf definitions. ``usd`` is resolved relative to <ext>/assets at runtime;
# ``prim_prefix`` is the default stage path the asset is referenced under.
VENDOR = "e-con"
CAMERAS = [
    {
        "name": "DepthVista Helix iToF (USB)",
        "usd": "DEPTH_VISTA_HELIX_USB.usd",
        "prim_prefix": "/DEPTH_VISTA_HELIX_USB",
    },
    {
        "name": "DepthVista Helix iToF (GMSL)",
        "usd": "DEPTH_VISTA_HELIX_GMSL.usd",
        "prim_prefix": "/DEPTH_VISTA_HELIX_GMSL",
    },
]


class Extension(omni.ext.IExt):
    """Registers the e-con submenu on startup and tears it down on shutdown."""

    def on_startup(self, ext_id: str):
        self._ext_id = ext_id
        ext_path = omni.kit.app.get_app().get_extension_manager().get_extension_path(ext_id)
        self._asset_dir = os.path.join(ext_path, "assets")

        leaves = []
        for cam in CAMERAS:
            usd_path = os.path.join(self._asset_dir, cam["usd"])
            prim_prefix = cam["prim_prefix"]
            # Bind loop values as defaults so each callback keeps its own asset.
            leaves.append(MenuItemDescription(
                name=cam["name"],
                onclick_fn=lambda up=usd_path, pp=prim_prefix: self._add_camera(up, pp),
            ))

        # Nested by name so add_menu_items merges into the existing menu path:
        #   Create > Sensors > Camera and Depth Sensors > e-con > <leaves>
        self._menu_items = [
            MenuItemDescription(name="Sensors", sub_menu=[
                MenuItemDescription(name="Camera and Depth Sensors", sub_menu=[
                    MenuItemDescription(name=VENDOR, sub_menu=leaves),
                ]),
            ]),
        ]
        add_menu_items(self._menu_items, "Create")
        carb.log_info(f"[econ.itof.menu] added '{VENDOR}' camera menu ({len(CAMERAS)} entries)")

    def on_shutdown(self):
        if getattr(self, "_menu_items", None):
            remove_menu_items(self._menu_items, "Create")
            self._menu_items = None
        gc.collect()

    # ── helpers ────────────────────────────────────────────────────────────────
    def _add_camera(self, usd_path: str, prim_prefix: str):
        """Add the asset as a reference at the next free prim path and select it."""
        if not os.path.isfile(usd_path):
            carb.log_error(f"[econ.itof.menu] asset not found: {usd_path}")
            return

        stage = omni.usd.get_context().get_stage()
        if stage is None:
            carb.log_error("[econ.itof.menu] no stage open")
            return

        prim_path = self._next_free_path(stage, prim_prefix)
        # USD reference paths use forward slashes on every OS.
        asset_uri = usd_path.replace(os.sep, "/")
        try:
            prim = stage.DefinePrim(prim_path, "Xform")
            prim.GetReferences().AddReference(asset_uri)
            omni.usd.get_context().get_selection().set_selected_prim_paths([prim_path], True)
            carb.log_info(f"[econ.itof.menu] added {prim_path} -> {asset_uri}")
        except Exception as exc:  # noqa: BLE001 — surface, never crash the menu
            carb.log_error(f"[econ.itof.menu] failed to add {asset_uri}: {exc}")

    @staticmethod
    def _next_free_path(stage, base: str) -> str:
        """Return ``base`` if free, else ``base_01``, ``base_02``, … (deterministic)."""
        if not stage.GetPrimAtPath(base).IsValid():
            return base
        i = 1
        while True:
            candidate = f"{base}_{i:02d}"
            if not stage.GetPrimAtPath(candidate).IsValid():
                return candidate
            i += 1
