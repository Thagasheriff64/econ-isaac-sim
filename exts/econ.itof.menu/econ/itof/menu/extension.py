"""Adds e-con DepthVista Helix iToF cameras to the Isaac Sim Create menu.

Mirrors the pattern of NVIDIA's stock ``isaacsim.sensors.camera.ui`` extension:
each leaf registers an action and the submenu is published with
``isaacsim.gui.components.menu.create_submenu`` + ``omni.kit.menu.utils.add_menu_items``.
Because Kit menus merge by name, our ``e-con`` vendor appears under the existing
``Create > Sensors > Camera and Depth Sensors`` path, alongside Intel/Orbbec/Stereolabs.

Difference from the NVIDIA extension: our entries are plain reference USDs (not RTX
sensor configs), so the click handler adds the asset as a stage reference rather than
calling ``RtxCamera.create``. The dropped prim (``DEPTH_VISTA_HELIX_USB`` / ``_GMSL``)
is exactly what ``isaac_usd_ros_itof.py`` discovers for ROS 2 streaming.
"""

import gc
import os

import carb
import omni.ext
import omni.kit.actions.core
import omni.kit.app
import omni.usd

from isaacsim.gui.components.menu import create_submenu
from omni.kit.menu.utils import add_menu_items, remove_menu_items


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
        self._ext_name = omni.ext.get_extension_name(ext_id)
        self._registered_actions = []

        ext_path = omni.kit.app.get_app().get_extension_manager().get_extension_path(ext_id)
        self._asset_dir = os.path.join(ext_path, "assets")

        action_registry = omni.kit.actions.core.get_action_registry()

        sensor_items = []
        for cam in CAMERAS:
            usd_path = os.path.join(self._asset_dir, cam["usd"])
            prim_prefix = cam["prim_prefix"]

            action_id = "create_" + cam["usd"].lower().replace(".", "_")
            # Bind loop values as defaults so each lambda keeps its own asset.
            action_fn = lambda *_, up=usd_path, pp=prim_prefix: self._add_camera(up, pp)
            action_registry.register_action(
                self._ext_name, action_id, action_fn,
                description=f"Add {cam['name']} to the stage",
            )
            self._registered_actions.append(action_id)
            sensor_items.append({"name": cam["name"], "onclick_action": (self._ext_name, action_id)})

        # Same nested dict shape create_submenu expects (verified against the stock
        # isaacsim.sensors.camera.ui extension); merges into the existing menu by name.
        sensors_menu_dict = {
            "name": {
                "Sensors": [
                    {"name": {"Camera and Depth Sensors": [
                        {"name": {VENDOR: sensor_items}},
                    ]}},
                ]
            },
        }
        self._menu_items = create_submenu(sensors_menu_dict)
        add_menu_items(self._menu_items, "Create")
        carb.log_info(f"[econ.itof.menu] added '{VENDOR}' camera menu ({len(CAMERAS)} entries)")

    def on_shutdown(self):
        if getattr(self, "_menu_items", None) is not None:
            remove_menu_items(self._menu_items, "Create")
            self._menu_items = None

        action_registry = omni.kit.actions.core.get_action_registry()
        for action_id in self._registered_actions:
            action_registry.deregister_action(self._ext_name, action_id)
        self._registered_actions.clear()
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
