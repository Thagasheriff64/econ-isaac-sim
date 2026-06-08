#!/usr/bin/env python3
"""ROS 2 publisher for e-con DepthVista Helix ToF cameras in Isaac Sim 5.1.

Both camera types (GMSL and USB) are auto-detected in the stage — there is no
variant argument.  Every DepthVista unit found becomes its own camera, numbered
by discovery order and tagged with its real type::

    cam0_gmsl, cam1_usb, cam2_gmsl, …

Each unit publishes (``<ns>`` = ``/tof/cam{i}_{type}``)::

    <ns>/highres/{depth, camera_info, points}     1280x960  0.2-2.0 m
    <ns>/longrange/{depth, camera_info, points}    640x480  0.5-6.0 m
    <ns>/imu                                       6-axis IMU @ 416 Hz
    /clock  /tf                                    (shared, once)

highres and longrange are the same physical module, so they share one IMU and
one flat TF frame per unit; every unit frame is a child of ``TF_WORLD_FRAME``.

Cameras listed in ``IMU_PRINT_CAMERAS`` get an on-screen ToString -> PrintText
readout of the IMU (axes toggled by ``IMU_{ANGULAR,LINEAR}_TO_SCREEN``), so IMU
data can be inspected without RViz or the ros2 CLI.

Usage (Isaac Sim Script Editor / VS Code):
    Run this file to start publishing.
    Stop   : Ctrl+Alt+R (Isaac viewport focused) or call ``teardown()``.
             Also stops the timeline when ``STOP_SIM_ON_EXIT`` is True.
    Re-run : execute the file again; stale graphs and the hotkey auto-reset.
"""

import asyncio

try:
    import omni.usd
    import omni.kit.app
    import omni.timeline
    import omni.graph.core as og
    from pxr import Usd, UsdGeom, Gf, Sdf
    _HAVE_ISAAC = True
except ImportError:
    _HAVE_ISAAC = False
    print("[ros2_itof] WARNING: not running inside Isaac Sim.")


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

# --- ROS 2 / TF ---------------------------------------------------------------
ROS2_DOMAIN_ID = 1          # must match ROS_DOMAIN_ID in your shell
TOPIC_ROOT     = "/tof"     # root namespace for all camera/imu topics
TF_WORLD_FRAME = "world"    # global/parent frame name (RViz "Fixed Frame")
TF_PARENT_PRIM = ""         # "" -> frames are world-relative.  Set a prim path
                            # (e.g. a robot base) to parent all frames under it;
                            # that prim is then named TF_WORLD_FRAME.

# --- IMU ----------------------------------------------------------------------
IMU_READ_GRAVITY = True     # True  -> realistic accel incl. gravity (~9.81 g at
                            #          rest, like the real ISM330DHCX)
                            # False -> motion-only acceleration (0 at rest)

# On-screen IMU readout, selectable per camera (there can be many):
#   []      -> none      [0, 2] -> those camera indices      "all" -> every camera
IMU_PRINT_CAMERAS     = [0]
IMU_LINEAR_TO_SCREEN  = True   # show linAcc overlay for the selected cameras
IMU_ANGULAR_TO_SCREEN = True   # show angVel overlay for the selected cameras

# --- Lifecycle ----------------------------------------------------------------
STOP_SIM_ON_EXIT = True     # True  -> Ctrl+Alt+R / teardown() also stops the
                            #          timeline (toolbar returns to play)
                            # False -> keep the simulation playing on stop

# Asset prim names mapped to a short type tag.  A unit is any prim whose name
# matches one of these (or "<name>_NN" for duplicates) and has a ToF_Camera child.
_ASSET_TYPES = {
    "DEPTH_VISTA_HELIX_GMSL": "gmsl",
    "DEPTH_VISTA_HELIX_USB":  "usb",
}


# ══════════════════════════════════════════════════════════════════════════════
# SENSOR CONSTANTS  (onsemi AF0130 + e-con DepthVista Helix)
# ══════════════════════════════════════════════════════════════════════════════

_PIXEL_PITCH_MM  = 3.5e-3
_W_FULL, _H_FULL = 1280, 960
_W_VGA,  _H_VGA  = 640,  480
_SENSOR_W_MM     = _W_FULL * _PIXEL_PITCH_MM   # 4.480 mm
_SENSOR_H_MM     = _H_FULL * _PIXEL_PITCH_MM   # 3.360 mm
_FL_MM           = 4.14
_FX_FULL         = 1183.0
_FX_VGA          = _FX_FULL / 2.0              # 591.5 px


def _make_params(fx: float, width: int, height: int,
                 near_m: float, far_m: float) -> dict:
    """Build the intrinsics/clipping descriptor for one camera resolution."""
    return dict(fx=fx, fy=fx, cx=width / 2.0, cy=height / 2.0,
                width=width, height=height, near_m=near_m, far_m=far_m)


# Per-resolution config (camera prim names are identical in the GMSL/USB builds).
_CAMERA_CONFIGS = {
    "highres": {
        "prim_name": "econ_iToF_highResolution",
        "params":    _make_params(_FX_FULL, _W_FULL, _H_FULL, 0.2, 2.0),
    },
    "longrange": {
        "prim_name": "econ_iToF_longRange",
        "params":    _make_params(_FX_VGA, _W_VGA, _H_VGA, 0.5, 6.0),
    },
}

# Camera prims under these prefixes are render/editor cameras, never our sensors.
_SKIP_PREFIXES = ("/OmniverseKit_", "/Render/")


# ══════════════════════════════════════════════════════════════════════════════
# MODULE STATE
# ══════════════════════════════════════════════════════════════════════════════
#
# Graphs are created dynamically (the count depends on how many units are in the
# scene), so there is no static path list — cleanup scans for top-level /ROS2*
# prims instead.  The hotkey watcher is the only long-lived runtime object.

_hotkey_watcher = None


# ══════════════════════════════════════════════════════════════════════════════
# STAGE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _stage_mpu(stage) -> float:
    """Return the stage's metersPerUnit, defaulting to 1.0 if unset."""
    v = UsdGeom.GetStageMetersPerUnit(stage)
    return v if v and v > 0.0 else 1.0


def _find_asset_roots(stage) -> list:
    """Find every DepthVista unit (GMSL or USB), including duplicates loaded as
    ``<name>_01`` / ``_02``.  Returns ``(path, type)`` pairs sorted by path so the
    discovery order — and therefore cam0, cam1, … — is deterministic.
    """
    found = []
    for prim in stage.Traverse():
        if not prim.GetChild("ToF_Camera").IsValid():
            continue
        name = prim.GetName()
        for asset_name, type_tag in _ASSET_TYPES.items():
            if name == asset_name or name.startswith(asset_name + "_"):
                found.append((str(prim.GetPath()), type_tag))
                break
    return sorted(found)


def _find_camera(stage, unit_root: str, prim_name: str) -> "str | None":
    """Locate a camera prim *within one unit's subtree*.

    Scoping to the unit matters: two identical units share camera prim names, so
    a stage-wide search would return the wrong unit's camera.
    """
    direct = f"{unit_root}/ToF_Camera/CameraFrame/{prim_name}"
    if stage.GetPrimAtPath(direct).IsValid():
        print(f"  [find] {prim_name:32s} -> {direct}")
        return direct

    root_prim = stage.GetPrimAtPath(unit_root)
    if root_prim.IsValid():
        for prim in Usd.PrimRange(root_prim):
            if (prim.IsA(UsdGeom.Camera) and prim.GetName() == prim_name
                    and not _is_skipped(prim)):
                print(f"  [find] {prim_name:32s} -> {prim.GetPath()}")
                return str(prim.GetPath())

    print(f"  [find] ERROR: '{prim_name}' not found under {unit_root}.")
    return None


def _find_imu(stage, unit_root: str) -> "str | None":
    """Locate the IsmImuSensor prim under a unit (build-layout agnostic)."""
    for candidate in (f"{unit_root}/ToF_Camera/IMU/ImuBody/IsmImuSensor",
                      f"{unit_root}/ToF_Camera/IMU/IsmImuSensor"):
        if stage.GetPrimAtPath(candidate).IsValid():
            return candidate
    for prim in stage.Traverse():
        if prim.GetName() == "IsmImuSensor" and str(prim.GetPath()).startswith(unit_root):
            return str(prim.GetPath())
    return None


def _is_skipped(prim) -> bool:
    return any(str(prim.GetPath()).startswith(pfx) for pfx in _SKIP_PREFIXES)


def _set_frame_name(stage, prim_path: str, name: str):
    """Author ``isaac:nameOverride`` so the TF frame published for this prim is
    exactly ``name`` — matching the frame_id we put on its topics.

    Without it the TF publisher names the frame after the prim (auto-renaming
    duplicates), so a point cloud's frame_id wouldn't match TF and RViz couldn't
    transform it into the world frame.
    """
    prim = stage.GetPrimAtPath(prim_path)
    if prim and prim.IsValid():
        prim.CreateAttribute("isaac:nameOverride", Sdf.ValueTypeNames.String).Set(name)


def _bake_intrinsics(stage, cam_path: str, params: dict):
    """Write the AF0130 intrinsics/clipping onto a USD camera prim.  These define
    the render frustum, and ROS2CameraInfoHelper reads them back into CameraInfo.
    """
    prim = stage.GetPrimAtPath(cam_path)
    if not prim.IsValid():
        print(f"  [bake] not found: {cam_path}")
        return
    cam = UsdGeom.Camera(prim)
    mpu = _stage_mpu(stage)
    cam.GetHorizontalApertureAttr().Set(float(_SENSOR_W_MM))
    cam.GetVerticalApertureAttr().Set(float(_SENSOR_H_MM))
    cam.GetFocalLengthAttr().Set(float(_FL_MM))
    cam.GetHorizontalApertureOffsetAttr().Set(0.0)
    cam.GetVerticalApertureOffsetAttr().Set(0.0)
    cam.GetClippingRangeAttr().Set(
        Gf.Vec2f(params["near_m"] / mpu, params["far_m"] / mpu))
    print(f"  [bake] {cam_path.split('/')[-1]:32s} fl={_FL_MM}mm "
          f"fx={params['fx']:.1f}px  "
          f"clip={params['near_m']/mpu:.3f}-{params['far_m']/mpu:.3f} wu")


async def _wait(frames: int):
    """Yield for ``frames`` app updates so render products / graphs settle."""
    app = omni.kit.app.get_app()
    for _ in range(frames):
        await app.next_update_async()


# ══════════════════════════════════════════════════════════════════════════════
# OMNIGRAPH BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _og_edit(graph_path: str, spec: dict, label: str) -> bool:
    """Create (replacing any existing) an execution OmniGraph from ``spec``.
    Returns True on success; logs and returns False on failure.
    """
    stage = omni.usd.get_context().get_stage()
    if stage.GetPrimAtPath(graph_path).IsValid():
        stage.RemovePrim(graph_path)
        omni.kit.app.get_app().update()
    try:
        og.Controller.edit(
            {"graph_path": graph_path, "evaluator_name": "execution"}, spec)
        print(f"  [graph] {label}  OK")
        return True
    except Exception as exc:
        print(f"  [graph] {label}  FAILED: {exc}")
        return False


def _setup_shared(tf_targets: list, parent_prim: str = ""):
    """Build the once-per-scene graph publishing ``/clock`` and ``/tf``."""
    values = [
        ("Ctx.inputs:domain_id",   ROS2_DOMAIN_ID),
        ("Clock.inputs:topicName", "/clock"),
        ("TF.inputs:topicName",    "/tf"),
        ("TF.inputs:targetPrims",  tf_targets),
    ]
    if parent_prim:
        values.append(("TF.inputs:parentPrim", [parent_prim]))

    _og_edit("/ROS2SharedGraph", {
        og.Controller.Keys.CREATE_NODES: [
            ("OnTick",  "omni.graph.action.OnPlaybackTick"),
            ("Ctx",     "isaacsim.ros2.bridge.ROS2Context"),
            ("SimTime", "isaacsim.core.nodes.IsaacReadSimulationTime"),
            ("Clock",   "isaacsim.ros2.bridge.ROS2PublishClock"),
            ("TF",      "isaacsim.ros2.bridge.ROS2PublishTransformTree"),
        ],
        og.Controller.Keys.CONNECT: [
            ("OnTick.outputs:tick",            "Clock.inputs:execIn"),
            ("SimTime.outputs:simulationTime", "Clock.inputs:timeStamp"),
            ("Ctx.outputs:context",            "Clock.inputs:context"),
            ("OnTick.outputs:tick",            "TF.inputs:execIn"),
            ("Ctx.outputs:context",            "TF.inputs:context"),
            ("SimTime.outputs:simulationTime", "TF.inputs:timeStamp"),
        ],
        og.Controller.Keys.SET_VALUES: values,
    }, "/ROS2SharedGraph  /clock + /tf")


def _setup_camera_graph(graph_path: str, cam_path: str, frame_id: str,
                        topic_ns: str, width: int, height: int):
    """Build one camera's graph: depth + camera_info + points.

    IsaacCreateRenderProduct builds the render product inside the graph and feeds
    its path to each publisher.  depth/points use ROS2CameraHelper; camera_info
    needs ROS2CameraInfoHelper ("camera_info" is not a ROS2CameraHelper type).
    """
    _og_edit(graph_path, {
        og.Controller.Keys.CREATE_NODES: [
            ("OnTick",     "omni.graph.action.OnPlaybackTick"),
            ("Ctx",        "isaacsim.ros2.bridge.ROS2Context"),
            ("RenderProd", "isaacsim.core.nodes.IsaacCreateRenderProduct"),
            ("Depth",      "isaacsim.ros2.bridge.ROS2CameraHelper"),
            ("PC",         "isaacsim.ros2.bridge.ROS2CameraHelper"),
            ("CamInfo",    "isaacsim.ros2.bridge.ROS2CameraInfoHelper"),
        ],
        og.Controller.Keys.CONNECT: [
            ("OnTick.outputs:tick",                  "RenderProd.inputs:execIn"),
            ("RenderProd.outputs:execOut",           "Depth.inputs:execIn"),
            ("RenderProd.outputs:execOut",           "PC.inputs:execIn"),
            ("RenderProd.outputs:execOut",           "CamInfo.inputs:execIn"),
            ("Ctx.outputs:context",                  "Depth.inputs:context"),
            ("Ctx.outputs:context",                  "PC.inputs:context"),
            ("Ctx.outputs:context",                  "CamInfo.inputs:context"),
            ("RenderProd.outputs:renderProductPath", "Depth.inputs:renderProductPath"),
            ("RenderProd.outputs:renderProductPath", "PC.inputs:renderProductPath"),
            ("RenderProd.outputs:renderProductPath", "CamInfo.inputs:renderProductPath"),
        ],
        og.Controller.Keys.SET_VALUES: [
            ("Ctx.inputs:domain_id",         ROS2_DOMAIN_ID),
            ("RenderProd.inputs:cameraPrim", [cam_path]),
            ("RenderProd.inputs:width",      int(width)),
            ("RenderProd.inputs:height",     int(height)),
            ("Depth.inputs:type",            "depth"),
            ("Depth.inputs:topicName",       f"{topic_ns}/depth"),
            ("Depth.inputs:frameId",         frame_id),
            ("PC.inputs:type",               "depth_pcl"),
            ("PC.inputs:topicName",          f"{topic_ns}/points"),
            ("PC.inputs:frameId",            frame_id),
            ("CamInfo.inputs:topicName",     f"{topic_ns}/camera_info"),
            ("CamInfo.inputs:frameId",       frame_id),
        ],
    }, f"{graph_path}  ->  {topic_ns}/{{depth,camera_info,points}}")


# ── IMU graph + optional on-screen readout ─────────────────────────────────────
#
# One IMU graph per unit (highres/longrange share the module).  ROS2PublishImu
# has no execOut, so nothing chains after it.  The ToString -> PrintText readout
# is added in a separate, best-effort step so a missing node type can never break
# publishing.  ToString lives in omni.graph.nodes; PrintText in omni.graph.ui_nodes.

_TOSTRING_TYPE   = "omni.graph.nodes.ToString"
_PRINTTEXT_TYPES = ("omni.graph.ui_nodes.PrintText", "omni.graph.nodes.PrintText")
# Candidate names for ToString's string output (varies by Kit version).
_TOSTRING_OUTS   = ("outputs:converted", "outputs:string", "outputs:value", "outputs:output")


def _imu_print_enabled(index: int) -> bool:
    """Whether camera ``index`` should show the on-screen IMU readout."""
    return IMU_PRINT_CAMERAS == "all" or index in IMU_PRINT_CAMERAS


def _setup_imu(graph_path: str, imu_prim_path: str, topic: str,
               frame_id: str, show_on_screen: bool):
    """Build one unit's IMU graph (read + publish), then attach the readout."""
    ok = _og_edit(graph_path, {
        og.Controller.Keys.CREATE_NODES: [
            ("OnTick",  "omni.graph.action.OnPlaybackTick"),
            ("Ctx",     "isaacsim.ros2.bridge.ROS2Context"),
            ("SimTime", "isaacsim.core.nodes.IsaacReadSimulationTime"),
            ("ReadIMU", "isaacsim.sensors.physics.IsaacReadIMU"),
            ("PubIMU",  "isaacsim.ros2.bridge.ROS2PublishImu"),
        ],
        og.Controller.Keys.CONNECT: [
            ("OnTick.outputs:tick",            "ReadIMU.inputs:execIn"),
            ("ReadIMU.outputs:execOut",        "PubIMU.inputs:execIn"),
            ("Ctx.outputs:context",            "PubIMU.inputs:context"),
            ("SimTime.outputs:simulationTime", "PubIMU.inputs:timeStamp"),
            ("ReadIMU.outputs:linAcc",         "PubIMU.inputs:linearAcceleration"),
            ("ReadIMU.outputs:angVel",         "PubIMU.inputs:angularVelocity"),
            ("ReadIMU.outputs:orientation",    "PubIMU.inputs:orientation"),
        ],
        og.Controller.Keys.SET_VALUES: [
            ("Ctx.inputs:domain_id",       ROS2_DOMAIN_ID),
            ("ReadIMU.inputs:imuPrim",     [imu_prim_path]),
            ("ReadIMU.inputs:readGravity", IMU_READ_GRAVITY),
            ("PubIMU.inputs:topicName",    topic),
            ("PubIMU.inputs:frameId",      frame_id),
            ("PubIMU.inputs:queueSize",    1),
        ],
    }, f"{graph_path}  ->  {topic}")

    if ok:
        _add_imu_readout(graph_path, show_on_screen)


def _add_imu_readout(graph_path: str, show_on_screen: bool):
    """Attach a ToString -> PrintText viewport readout for angVel and linAcc.

    The branch is always built (so every IMU graph is identical); only each
    PrintText's ``toScreen`` differs, set from ``show_on_screen`` AND the
    per-axis flag.  Best-effort: each step is guarded so a missing node type or
    port name cannot affect the already-built publish graph.  Connections use
    absolute paths so the existing ReadIMU node resolves.
    """
    stage = omni.usd.get_context().get_stage()

    # Ensure the extensions providing ToString / PrintText are loaded.
    try:
        mgr = omni.kit.app.get_app().get_extension_manager()
        for ext in ("omni.graph.ui_nodes", "omni.graph.nodes"):
            if not mgr.is_extension_enabled(ext):
                mgr.set_extension_enabled_immediate(ext, True)
    except Exception:
        pass

    def remove(*names):
        for name in names:
            try:
                stage.RemovePrim(f"{graph_path}/{name}")
            except Exception:
                pass

    def connect(src: str, dst: str) -> bool:
        try:
            og.Controller.connect(f"{graph_path}/{src}", f"{graph_path}/{dst}")
            return True
        except Exception:
            return False

    # Create 2x ToString + 2x PrintText, trying each PrintText type until one works.
    print_type = None
    for candidate in _PRINTTEXT_TYPES:
        try:
            og.Controller.edit(graph_path, {
                og.Controller.Keys.CREATE_NODES: [
                    ("ToStrAng", _TOSTRING_TYPE),
                    ("ToStrLin", _TOSTRING_TYPE),
                    ("PrintAng", candidate),
                    ("PrintLin", candidate),
                ],
            })
            print_type = candidate
            break
        except Exception:
            remove("ToStrAng", "ToStrLin", "PrintAng", "PrintLin")
    if print_type is None:
        print("  [imu] readout skipped — no PrintText node type available (publishing OK)")
        return

    # Data + exec wiring.
    connect("ReadIMU.outputs:angVel",  "ToStrAng.inputs:value")
    connect("ReadIMU.outputs:linAcc",  "ToStrLin.inputs:value")
    connect("ReadIMU.outputs:execOut", "PrintAng.inputs:execIn")
    connect("ReadIMU.outputs:execOut", "PrintLin.inputs:execIn")

    # On-screen visibility per axis (graph is identical; only these booleans vary).
    for node, on in (("PrintAng", show_on_screen and IMU_ANGULAR_TO_SCREEN),
                     ("PrintLin", show_on_screen and IMU_LINEAR_TO_SCREEN)):
        try:
            og.Controller.attribute(f"{graph_path}/{node}.inputs:toScreen").set(bool(on))
        except Exception:
            pass

    # ToString output -> PrintText.text (output attr name varies by Kit version).
    linked = 0
    for tostr, prnt in (("ToStrAng", "PrintAng"), ("ToStrLin", "PrintLin")):
        for out in _TOSTRING_OUTS:
            if connect(f"{tostr}.{out}", f"{prnt}.inputs:text"):
                linked += 1
                break
    print(f"  [imu] readout: linked {linked}/2  (PrintText={print_type})")


def _verify_imu_sensor(imu_prim_path: str) -> bool:
    """Confirm the IMU prim exists.  No runtime PhysX API is applied: the build
    script authors it as an IsaacImuSensor with a kinematic rigid-body parent, so
    Isaac Sim activates the sensor automatically on load.
    """
    prim = omni.usd.get_context().get_stage().GetPrimAtPath(imu_prim_path)
    if not prim.IsValid():
        print(f"  [imu] prim not found: {imu_prim_path}")
        return False
    print(f"  [imu] sensor prim OK  (type={prim.GetTypeName()})")
    return True


# ══════════════════════════════════════════════════════════════════════════════
# ENVIRONMENT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _check_bridge() -> bool:
    """Return True if the ROS 2 bridge extension is enabled (warn otherwise)."""
    try:
        ok = omni.kit.app.get_app().get_extension_manager() \
                 .is_extension_enabled("isaacsim.ros2.bridge")
        if not ok:
            print("[ERROR] isaacsim.ros2.bridge not enabled — "
                  "Window -> Extensions -> search 'ros2 bridge' -> Enable")
        return ok
    except Exception:
        return True


async def _ensure_playing():
    """Press Play if the timeline is stopped (sensors need the sim running)."""
    try:
        timeline = omni.timeline.get_timeline_interface()
        if not timeline.is_playing():
            print("[timeline] pressing Play …")
            timeline.play()
            await _wait(10)
        else:
            print("[timeline] already playing")
    except Exception as exc:
        print(f"[timeline] {exc}")


def _remove_all_ros2_graphs(stage) -> int:
    """Remove every top-level graph this script creates (all named ``/ROS2*``)."""
    removed = 0
    for prim in list(stage.GetPseudoRoot().GetChildren()):
        if prim.GetName().startswith("ROS2") and stage.RemovePrim(prim.GetPath()):
            removed += 1
    return removed


def _reset_state():
    """Make re-running idempotent: drop a previous run's hotkey watcher and
    remove stale ``/ROS2*`` graphs, so the script can be executed again cleanly.
    """
    global _hotkey_watcher
    if _hotkey_watcher is not None:
        _hotkey_watcher.destroy()
        _hotkey_watcher = None
    if not _HAVE_ISAAC:
        return
    stage = omni.usd.get_context().get_stage()
    removed = _remove_all_ros2_graphs(stage)
    if removed:
        print(f"[reset] removed {removed} stale ROS2 graph(s) from a previous run")
        omni.kit.app.get_app().update()


# ══════════════════════════════════════════════════════════════════════════════
# STOP HOTKEY  (Ctrl+Alt+R)
# ══════════════════════════════════════════════════════════════════════════════
#
# Polls the app-window keyboard each frame, so it fires ONLY while an Isaac Sim
# window has OS focus.  Ctrl+Alt+R is chosen because it is not bound by default in
# GNOME, VS Code or common terminals and is not a quit/close action.  Polling does
# not consume the key, so the combo must be one nothing else grabs.  To rebind,
# edit the KeyboardInput checks in _poll().

class _HotkeyWatcher:
    """Edge-detected Ctrl+Alt+R that calls ``teardown()`` exactly once."""

    def __init__(self):
        import carb.input as ci
        import omni.appwindow
        self._ci       = ci
        self._kbd      = omni.appwindow.get_default_app_window().get_keyboard()
        self._iface    = ci.acquire_input_interface()
        self._pressed  = False
        self._stopping = False
        self._sub = omni.kit.app.get_app().get_update_event_stream() \
            .create_subscription_to_pop(self._poll, name="ros2_itof_hotkey")
        print("[hotkey] Ctrl+Alt+R stops ROS2"
              + (" + scene" if STOP_SIM_ON_EXIT else "")
              + " — only while the Isaac Sim window has focus (click the viewport "
                "first); otherwise call teardown() directly.")

    def _poll(self, _):
        if self._stopping:
            return
        ci = self._ci
        try:
            r    = self._iface.get_keyboard_value(self._kbd, ci.KeyboardInput.R) > 0.5
            alt  = (self._iface.get_keyboard_value(self._kbd, ci.KeyboardInput.LEFT_ALT)      > 0.5 or
                    self._iface.get_keyboard_value(self._kbd, ci.KeyboardInput.RIGHT_ALT)     > 0.5)
            ctrl = (self._iface.get_keyboard_value(self._kbd, ci.KeyboardInput.LEFT_CONTROL)  > 0.5 or
                    self._iface.get_keyboard_value(self._kbd, ci.KeyboardInput.RIGHT_CONTROL) > 0.5)
        except Exception:
            return
        pressed = r and ctrl and alt
        if pressed and not self._pressed:
            self._stopping = True   # block re-entry before teardown drops _sub
            print("\n[hotkey] Ctrl+Alt+R — stopping ROS2 …")
            teardown()
            return
        self._pressed = pressed

    def destroy(self):
        self._sub = None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    """Discover every DepthVista unit and build all ROS 2 publisher graphs."""
    print("\n" + "═" * 72)
    print("  isaac_ros_itof.py  —  Isaac Sim 5.1")
    print("  e-con DepthVista Helix (GMSL + USB auto-detected) | Sensor: onsemi AF0130")
    print(f"  IMU 6-axis 416 Hz  |  Domain {ROS2_DOMAIN_ID}  |  TF parent: {TF_WORLD_FRAME}")
    print("═" * 72 + "\n")

    if not _HAVE_ISAAC:
        print("[main] Must run inside Isaac Sim.")
        return None
    if not _check_bridge():
        return None

    _reset_state()
    stage = omni.usd.get_context().get_stage()
    await _wait(10)

    # ── STEP 1 — Playback ────────────────────────────────────────────────────
    print("[STEP 1] Playback …")
    await _ensure_playing()

    # ── STEP 2 — Stage units ─────────────────────────────────────────────────
    print("\n[STEP 2] Stage units …")
    mpu = _stage_mpu(stage)
    print(f"  metersPerUnit = {mpu}")
    if abs(mpu - 1.0) > 1e-6:
        print("  WARNING: stage not in metres — depth values will be in stage units")

    # ── STEP 3 — Discover units ──────────────────────────────────────────────
    print("\n[STEP 3] Discovering DepthVista units (GMSL + USB) …")
    roots = _find_asset_roots(stage)
    if not roots:
        print("[FATAL] No DepthVista unit found. Load a USD first.")
        return None
    print(f"  found {len(roots)} unit(s)")

    units = []
    for index, (root, type_tag) in enumerate(roots):
        unit_id   = f"cam{index}_{type_tag}"     # always suffixed, e.g. cam0_gmsl
        ns_prefix = f"{TOPIC_ROOT}/{unit_id}"
        graph_tag = unit_id.upper()

        cams = {}
        for key, cfg in _CAMERA_CONFIGS.items():
            cam_path = _find_camera(stage, root, cfg["prim_name"])
            if cam_path is None:
                print(f"[FATAL] Camera '{cfg['prim_name']}' not found in {root}.")
                return None
            cams[key] = dict(
                path       = cam_path,
                params     = cfg["params"],
                frame_id   = unit_id,             # one flat frame per unit
                topic_ns   = f"{ns_prefix}/{key}",
                graph_path = f"/ROS2Camera_{graph_tag}_{key.upper()}",
            )

        # One TF frame per unit, anchored on the highres camera (optical centre);
        # every topic of the unit tags it, and only it is published to TF.
        frame_prim = cams.get("highres", next(iter(cams.values())))["path"]
        _set_frame_name(stage, frame_prim, unit_id)

        imu_prim = _find_imu(stage, root)
        units.append(dict(
            index      = index,
            unit_id    = unit_id,
            root       = root,
            cams       = cams,
            frame_prim = frame_prim,
            imu_prim   = imu_prim,
            imu_topic  = f"{ns_prefix}/imu",
            imu_frame  = unit_id,                 # imu shares the unit frame
            imu_graph  = f"/ROS2ImuGraph_{graph_tag}",
            imu_print  = _imu_print_enabled(index),
        ))
        print(f"  unit[{index}] {unit_id}   {root}   IMU: {imu_prim or 'NOT FOUND'}")

    # ── STEP 4 — Bake intrinsics ─────────────────────────────────────────────
    print("\n[STEP 4] Baking intrinsics …")
    for unit in units:
        for cam in unit["cams"].values():
            _bake_intrinsics(stage, cam["path"], cam["params"])
    await _wait(5)

    # ── STEP 5 — Verify IMU sensors ──────────────────────────────────────────
    print("\n[STEP 5] Verifying IMU sensors …")
    for unit in units:
        unit["imu_ok"] = bool(unit["imu_prim"]) and _verify_imu_sensor(unit["imu_prim"])

    # ── STEP 6 — Shared graph (/clock + /tf) ─────────────────────────────────
    print("\n[STEP 6] Shared graph …")
    tf_targets = [unit["frame_prim"] for unit in units]
    parent = TF_PARENT_PRIM if (TF_PARENT_PRIM and
                                stage.GetPrimAtPath(TF_PARENT_PRIM).IsValid()) else ""
    if parent:
        _set_frame_name(stage, parent, TF_WORLD_FRAME)
    _setup_shared(tf_targets, parent)

    # ── STEP 7 — Per-unit camera graphs ──────────────────────────────────────
    print("\n[STEP 7] Camera graphs …")
    for unit in units:
        for cam in unit["cams"].values():
            params = cam["params"]
            _setup_camera_graph(cam["graph_path"], cam["path"], cam["frame_id"],
                                cam["topic_ns"], params["width"], params["height"])

    # ── STEP 8 — Per-unit IMU graphs ─────────────────────────────────────────
    print("\n[STEP 8] IMU graphs …")
    for unit in units:
        if unit["imu_ok"]:
            _setup_imu(unit["imu_graph"], unit["imu_prim"], unit["imu_topic"],
                       unit["imu_frame"], unit["imu_print"])
        else:
            print(f"  [imu] {unit['unit_id']} SKIPPED — no valid IMU sensor prim")

    # ── STEP 9 — Warm-up ─────────────────────────────────────────────────────
    print("\n[STEP 9] Warming up …")
    await _wait(10)

    _print_summary(units)

    global _hotkey_watcher
    _hotkey_watcher = _HotkeyWatcher()
    return True


def _print_summary(units: list):
    """Print the active topics, frames and controls."""
    n_graphs = 1 + sum(len(u["cams"]) + (1 if u["imu_ok"] else 0) for u in units)
    overlay_axes = "+".join(a for a, on in (("angVel", IMU_ANGULAR_TO_SCREEN),
                                            ("linAcc", IMU_LINEAR_TO_SCREEN)) if on)

    print("\n" + "═" * 72)
    print(f"  ROS 2 ACTIVE  —  {len(units)} unit(s), {n_graphs} graphs\n")
    for unit in units:
        print(f"  ── UNIT {unit['unit_id']}   frame={unit['unit_id']} -> "
              f"{TF_WORLD_FRAME}   ({unit['root']})")
        for cam in unit["cams"].values():
            ns, p = cam["topic_ns"], cam["params"]
            print(f"     {ns}/depth         32FC1 metres")
            print(f"     {ns}/camera_info   CameraInfo")
            print(f"     {ns}/points        PointCloud2   "
                  f"(fx={p['fx']:.1f}  {p['near_m']}-{p['far_m']} m)")
        if unit["imu_ok"]:
            tag = (f"   (+viewport: {overlay_axes})"
                   if unit["imu_print"] and overlay_axes else "")
            print(f"     {unit['imu_topic']:<22} Imu 416 Hz{tag}")
        print()
    print(f"  /ROS2SharedGraph  ->  /clock  /tf   (all unit frames -> {TF_WORLD_FRAME})")
    print()
    print("  RViz depth: Normalize=OFF  highres 0.2-2.0 | longrange 0.5-6.0")
    print("  Stop: Ctrl+Alt+R (viewport focused) or teardown()")
    print("═" * 72 + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# TEARDOWN
# ══════════════════════════════════════════════════════════════════════════════

def teardown():
    """Stop publishing: drop the hotkey, remove all ROS2 graphs, and (if
    ``STOP_SIM_ON_EXIT``) stop the timeline.  Safe to call repeatedly.
    """
    global _hotkey_watcher
    if _hotkey_watcher is not None:
        _hotkey_watcher.destroy()
        _hotkey_watcher = None

    if _HAVE_ISAAC:
        stage = omni.usd.get_context().get_stage()
        print(f"[teardown] removed {_remove_all_ros2_graphs(stage)} ROS2 graph(s)")
        if STOP_SIM_ON_EXIT:
            try:
                omni.timeline.get_timeline_interface().stop()
                print("[teardown] timeline STOPPED (STOP_SIM_ON_EXIT=True)")
            except Exception as exc:
                print(f"[teardown] could not stop timeline: {exc}")

    state = "ROS2 stopped + scene stopped" if STOP_SIM_ON_EXIT \
        else "ROS2 stopped (simulation still playing)"
    print(f"[teardown] {state}. Re-run the script to restart.")


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if _HAVE_ISAAC:
    async def _run():
        try:
            await main()
        except Exception:
            import traceback
            traceback.print_exc()
    asyncio.ensure_future(_run())
else:
    asyncio.run(main())
