#!/usr/bin/env python3
"""ROS 2 publisher for e-con DepthVista Helix iToF cameras in Isaac Sim.

DepthVista units are auto-detected in the stage — there is no variant argument.
A single unit is simply ``cam``; when more than one is present they are numbered
by discovery order (``cam0``, ``cam1``, …).  A unit built as the suffixed GMSL/USB
asset additionally carries its type tag::

    cam                           (one unit, unsuffixed build)
    cam0, cam1, …                 (multiple units)
    cam_gmsl  /  cam0_usb, …      (explicit GMSL/USB builds)

Each unit publishes (``<ns>`` = ``/tof/cam[{i}][_{type}]``)::

    <ns>/highres/{depth, camera_info, points}     1280x960  0.2-2.0 m
    <ns>/longrange/{depth, camera_info, points}    640x480  0.5-6.0 m
    <ns>/imu                                       6-axis IMU @ 416 Hz
    /clock  /tf                                    (shared, once)

highres and longrange are the same physical module, so they share one IMU and
one flat TF frame per unit; every unit frame is a child of ``TF_WORLD_FRAME``.

Cameras listed in ``IMU_PRINT_CAMERAS`` get an on-screen ToString -> PrintText
readout of the IMU (axes toggled by ``IMU_{ANGULAR,LINEAR}_TO_SCREEN``), so IMU
data can be inspected without RViz or the ros2 CLI.

Setting ``WEB_VIEWER`` True additionally serves a localhost web page showing the
live, colour-mapped depth of every camera (with a probe readout of the metric
distance) plus interactive 3D point clouds for any selected cameras (orbit/zoom,
export to .ply), so the data can be inspected in a browser without RViz.  It
runs alongside ROS 2.

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

# On-screen IMU readout — 3 settings.  Keep IMU_PRINT_CAMERAS to a single camera;
# more than one overlay is unreadable on screen.
#   IMU_PRINT_CAMERAS : []=none   [0, 2]=those camera indices   "all"=every camera
IMU_PRINT_CAMERAS     = [0]
IMU_LINEAR_TO_SCREEN  = True    # overlay linear acceleration for the selected camera(s)
IMU_ANGULAR_TO_SCREEN = False   # overlay angular velocity for the selected camera(s)

# --- Camera intrinsics --------------------------------------------------------
# True  -> bake the AF0130 aperture/focal length/offsets (and clip, below) onto
#          each camera, guaranteeing CameraInfo even on a non-baked asset.
# False -> leave the camera untouched and just stream it as authored in the USD.
#          The shipped DepthVista asset already has the correct intrinsics, so
#          False is safe and never overrides your manual camera params.
BAKE_INTRINSICS = True

# Render-frustum near clip, in metres — an OPTICS value, NOT the ToF min range.
# Kept small so geometry closer than the ToF minimum still renders (you see the
# near object) instead of being culled, which makes the camera "see through" it.
# Only applied when BAKE_INTRINSICS is True; set None to leave the clip untouched.
RENDER_NEAR_M = 0.01

# --- Lifecycle ----------------------------------------------------------------
STOP_SIM_ON_EXIT = True     # True  -> Ctrl+Alt+R / teardown() also stops the
                            #          timeline (toolbar returns to play)
                            # False -> keep the simulation playing on stop

# --- Web viewer ---------------------------------------------------------------
# Optional browser preview of the live depth feed, served from inside Isaac Sim.
# It runs alongside ROS 2 (purely additive) and lets you inspect depth without
# RViz: open the printed URL to see each camera's colour-mapped depth (with a
# distance probe) and interactive point clouds.  No dependency beyond NumPy.
WEB_VIEWER       = True     # True -> start the localhost viewer
WEB_VIEWER_PORT  = 8211      # served at http://localhost:<port>/
WEB_VIEWER_HZ    = 10        # frame refresh rate (Hz)
WEB_VIEWER_MAX_W = 640       # cap preview width (px); keeps the extra render light

# Asset prim names mapped to a short type tag.  A unit is any prim whose name
# matches one of these (or "<name>_NN" for duplicates) and has a ToF_Camera child.
# The Create-menu build is added as the unsuffixed "DEPTHVISTA_HELIX" and gets an
# empty tag (so it is numbered cam0, cam1, … with no _gmsl/_usb suffix); the
# suffixed names are matched first so an explicit GMSL/USB build is still tagged.
_ASSET_TYPES = {
    "DEPTHVISTA_HELIX_GMSL": "gmsl",
    "DEPTHVISTA_HELIX_USB":  "usb",
    "DEPTHVISTA_HELIX":      "",
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
# scene) and all live under the GRAPH_ROOT container, so cleanup just removes
# that container (plus any legacy root-level /ROS2* prims).  The hotkey watcher
# and the optional web viewer are the only long-lived runtime objects.

_hotkey_watcher = None
_web_viewer     = None


# ══════════════════════════════════════════════════════════════════════════════
# STAGE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _stage_mpu(stage) -> float:
    """Return the stage's metersPerUnit, defaulting to 1.0 if unset."""
    v = UsdGeom.GetStageMetersPerUnit(stage)
    return v if v and v > 0.0 else 1.0


def _find_asset_roots(stage) -> list:
    """Find every DepthVista unit (GMSL, USB, or unsuffixed), including duplicates
    loaded as ``<name>_01`` / ``_02``.  Returns ``(path, type)`` pairs sorted by
    path so the discovery order — and therefore cam0, cam1, … — is deterministic.

    Names are matched most-specific first, so ``DEPTHVISTA_HELIX_GMSL`` is tagged
    ``gmsl`` rather than being swallowed by the unsuffixed ``DEPTHVISTA_HELIX``.
    """
    names_by_specificity = sorted(_ASSET_TYPES, key=len, reverse=True)
    found = []
    for prim in stage.Traverse():
        if not prim.GetChild("ToF_Camera").IsValid():
            continue
        name = prim.GetName()
        for asset_name in names_by_specificity:
            if name == asset_name or name.startswith(asset_name + "_"):
                found.append((str(prim.GetPath()), _ASSET_TYPES[asset_name]))
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
    """Author ``isaac:nameOverride`` so this prim's published TF frame is exactly
    ``name`` (matching the frame_id on its topics).  Otherwise the TF publisher
    names the frame after the prim and renames duplicates, so a point cloud's
    frame_id would not match TF and RViz could not transform it.
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
    # Near clip is the render-frustum optics (RENDER_NEAR_M), NOT the ToF min
    # range — keeping it small avoids culling close geometry (no see-through).
    # The ToF range stays the camera's near_m/far_m, used for the depth colouring.
    if RENDER_NEAR_M is not None:
        near = RENDER_NEAR_M / mpu
        cam.GetClippingRangeAttr().Set(Gf.Vec2f(near, params["far_m"] / mpu))
        clip = f"{near:.3f}-{params['far_m']/mpu:.3f}"
    else:
        clip = "asset"
    print(f"  [bake] {cam_path.split('/')[-1]:32s} fl={_FL_MM}mm "
          f"fx={params['fx']:.1f}px  clip={clip} wu")


async def _wait(frames: int):
    """Yield for ``frames`` app updates so render products / graphs settle."""
    app = omni.kit.app.get_app()
    for _ in range(frames):
        await app.next_update_async()


# ══════════════════════════════════════════════════════════════════════════════
# OMNIGRAPH BUILDER
# ══════════════════════════════════════════════════════════════════════════════

# Parent prim that holds every graph this script creates, so they appear nested
# under a single "Graphs" node in the stage instead of cluttering the root.
GRAPH_ROOT = "/Graphs"


def _ensure_scope(stage, path: str):
    """Create a USD Scope at ``path`` (used to group graphs) if it does not exist."""
    if not stage.GetPrimAtPath(path).IsValid():
        stage.DefinePrim(path, "Scope")


def _ensure_graph_root(stage):
    """Create the parent ``Graphs`` prim that all ROS 2 graphs live under.

    A Scope is used deliberately: graphs nested inside an *OmniGraph*-typed prim
    become subgraphs and stop receiving playback ticks (verified — the publishers
    go silent), whereas a Scope keeps each child a first-class, ticking graph.
    """
    if not stage.GetPrimAtPath(GRAPH_ROOT).IsValid():
        stage.DefinePrim(GRAPH_ROOT, "Scope")


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

    _og_edit(f"{GRAPH_ROOT}/ROS2SharedGraph", {
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
    }, f"{GRAPH_ROOT}/ROS2SharedGraph  /clock + /tf")


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
# One IMU graph per unit (highres/longrange share the module).  The ToString ->
# PrintText readout is attached as a separate, best-effort step so a missing node
# type can never break publishing.  Node types / port names vary by Kit version,
# hence the candidate lists below.

_TOSTRING_TYPE   = "omni.graph.nodes.ToString"
_PRINTTEXT_TYPES = ("omni.graph.ui_nodes.PrintText", "omni.graph.nodes.PrintText")
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

    Always built, so every IMU graph is identical; only each PrintText's
    ``toScreen`` differs (``show_on_screen`` AND the per-axis flag).  Every step
    is guarded, so a missing node type or port name cannot break the publish
    graph built above.
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
    """Remove the graphs this script creates: the ``GRAPH_ROOT`` container and
    any legacy root-level ``/ROS2*`` graphs left by older runs."""
    removed = 0
    for prim in list(stage.GetPseudoRoot().GetChildren()):
        if prim.GetName().startswith("ROS2") and stage.RemovePrim(prim.GetPath()):
            removed += 1
    if stage.GetPrimAtPath(GRAPH_ROOT).IsValid() and stage.RemovePrim(GRAPH_ROOT):
        removed += 1
    return removed


def _reset_state():
    """Make re-running idempotent: drop a previous run's hotkey watcher and
    remove stale ``/ROS2*`` graphs, so the script can be executed again cleanly.
    """
    global _hotkey_watcher, _web_viewer
    if _hotkey_watcher is not None:
        _hotkey_watcher.destroy()
        _hotkey_watcher = None
    if _web_viewer is not None:
        _web_viewer.destroy()
        _web_viewer = None
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
# window has OS focus.  Ctrl+Alt+R is unbound by default in GNOME / VS Code / most
# terminals and is not a quit action.  To rebind, edit the KeyboardInput checks in
# _poll().

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
# WEB VIEWER  (optional localhost depth preview)
# ══════════════════════════════════════════════════════════════════════════════
#
# Runs entirely inside the Isaac Sim process and alongside ROS 2.  A Replicator
# "distance_to_camera" annotator on each camera yields a metric depth array every
# frame; the latest frame per camera is buffered (as 16-bit millimetres) and a
# small threaded HTTP server hands it to the browser.  The page colour-maps depth
# over each camera's near/far range, reports the distance at a probe point (the
# cursor, else the last click, else the image centre), and renders an interactive
# 3D point cloud for any selected cameras — all client-side, from the raw depth.
#
# Threading note: annotator reads happen only on the app/update thread; the HTTP
# thread merely serves the buffered bytes under a lock (Kit is not thread-safe).

_WEB_VIEWER_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>e-con DepthVista — depth viewer</title>
<style>
 body{background:#111;color:#ddd;font:13px system-ui,sans-serif;margin:16px}
 h1{font-size:16px;font-weight:600}
 .cams{display:flex;flex-wrap:wrap;gap:18px}
 .cam{background:#1b1b1b;border:1px solid #333;border-radius:8px;padding:10px}
 .cam h2{font-size:13px;margin:0 0 6px}
 .cam canvas{image-rendering:pixelated;background:#000;border-radius:4px;cursor:crosshair;width:100%;height:auto}
 .read{margin-top:6px;font-variant-numeric:tabular-nums}
 .read b{color:#7ec8ff}
 .ctl{display:flex;align-items:center;gap:8px;margin:8px 0;font-size:12px;color:#aaa;flex-wrap:wrap}
 select,button{background:#222;color:#ddd;border:1px solid #444;border-radius:4px;padding:3px 8px}
 input[type=range]{width:110px}
 .pick{display:inline-flex;flex-wrap:wrap;gap:12px}
 .pick label{cursor:pointer}
 .pcards{display:flex;flex-wrap:wrap;gap:16px}
 .pcard{background:#1b1b1b;border:1px solid #333;border-radius:8px;padding:10px}
 .pcl-canvas{width:460px;height:360px;display:block;background:#0a0a0a;
   border:1px solid #333;border-radius:6px;margin-top:8px;cursor:grab}
 .info{color:#7ec8ff}
</style>
<script type="importmap">
{ "imports": { "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js" } }
</script>
</head><body>
<h1>e-con DepthVista — live depth (colour = distance)</h1>
<div class="cams" id="cams"></div>

<h1 style="margin-top:26px">Point clouds (colour = distance)</h1>
<div class="ctl">cameras: <span id="pcl-pick" class="pick"></span></div>
<div class="pcards" id="pcl-cards"></div>

<script>
const HZ = __HZ__;
function hsv(h){ // h in [0,360) -> [r,g,b] 0..255, full sat/val
  const c=1, x=1-Math.abs((h/60)%2-1);
  let r,g,b;
  if(h<60){r=c;g=x;b=0}else if(h<120){r=x;g=c;b=0}else if(h<180){r=0;g=c;b=x}
  else if(h<240){r=0;g=x;b=c}else if(h<300){r=x;g=0;b=c}else{r=c;g=0;b=x}
  return [r*255,g*255,b*255];
}
async function initTiles(){
  const cams = await (await fetch('cameras.json')).json();
  const root = document.getElementById('cams');
  for(const cam of cams){
    const W=cam.width, H=cam.height;
    const box=document.createElement('div'); box.className='cam';
    box.innerHTML=`<h2>${cam.label}  <span style="color:#888">${W}×${H}</span></h2>`;
    const cv=document.createElement('canvas'); cv.width=W; cv.height=H; cv.style.maxWidth='480px';
    const ctx=cv.getContext('2d'); const img=ctx.createImageData(W,H);
    const read=document.createElement('div'); read.className='read'; read.textContent='—';
    box.append(cv,read); root.append(box);
    // colour range is fixed to the camera's near/far (no slider)
    const near=cam.near*1000, far=Math.max(cam.far*1000, near+1), span=far-near;
    // probe point: cursor while hovering, else last click, else image centre
    const centre={x:(W>>1), y:(H>>1)};
    let hover=null, clicked=null, last=null;
    const toPix=e=>({x:Math.min(W-1,Math.max(0,Math.floor(e.offsetX/cv.clientWidth*W))),
                     y:Math.min(H-1,Math.max(0,Math.floor(e.offsetY/cv.clientHeight*H)))});
    cv.onmousemove=e=>hover=toPix(e);
    cv.onmouseleave=()=>hover=null;
    cv.onclick=e=>clicked=toPix(e);
    async function tick(){
      try{
        const buf=await (await fetch('depth/'+cam.id+'?t='+Date.now())).arrayBuffer();
        last=new Uint16Array(buf); const px=img.data;
        for(let i=0;i<last.length;i++){
          const v=last[i], o=i*4;
          if(!v){px[o]=px[o+1]=px[o+2]=18; px[o+3]=255; continue;}
          let t=(v-near)/span; t=t<0?0:t>1?1:t;
          const c=hsv((1-t)*240);           // near = blue, far = red
          px[o]=c[0]; px[o+1]=c[1]; px[o+2]=c[2]; px[o+3]=255;
        }
        ctx.putImageData(img,0,0);
        const p = hover||clicked||centre;
        const src = hover?'cursor':clicked?'clicked':'centre';
        const mm = last[p.y*W+p.x];
        read.innerHTML = `(${p.x}, ${p.y}) <span style="color:#777">${src}</span> → `+
          (mm?`<b>${(mm/1000).toFixed(3)} m</b>`:`<b>no return</b>`);
      }catch(_){}
    }
    setInterval(tick, 1000/HZ);
  }
}
initTiles();
</script>

<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js';

const HZ = __HZ__;
const STRIDE = 2;                 // sub-sample pixels to keep each cloud light
function hsv(h){
  const c=1, x=1-Math.abs((h/60)%2-1);
  let r,g,b;
  if(h<60){r=c;g=x;b=0}else if(h<120){r=x;g=c;b=0}else if(h<180){r=0;g=c;b=x}
  else if(h<240){r=0;g=x;b=c}else if(h<300){r=x;g=0;b=c}else{r=c;g=0;b=x}
  return [r*255,g*255,b*255];
}

const cardsWrap=document.getElementById('pcl-cards');
const pick=document.getElementById('pcl-pick');
let CAMS=[]; const cards=new Map();

// One interactive 3D point cloud, built in the browser from a camera's depth.
class PclCard{
  constructor(cam){
    this.cam=cam; this.alive=true; this.needFrame=true;
    this.opt=null; this.rgb=null; this.n=0;
    const card=document.createElement('div'); card.className='pcard';
    card.innerHTML=`<div class="ctl"><b>${cam.label}</b>`+
      ` point <input type="range" class="ps" min="1" max="6" step="0.5" value="2">`+
      ` <button class="dl">Download .ply</button> <span class="info"></span></div>`;
    const canvas=document.createElement('canvas'); canvas.className='pcl-canvas';
    card.append(canvas); cardsWrap.append(card);
    this.dom=card; this.info=card.querySelector('.info');

    const renderer=new THREE.WebGLRenderer({canvas, antialias:true});
    renderer.setPixelRatio(Math.min(devicePixelRatio,2));
    const scene=new THREE.Scene(); scene.background=new THREE.Color(0x0a0a0a);
    const view=new THREE.PerspectiveCamera(50,1,0.01,200); view.position.set(0,0,2);
    const controls=new OrbitControls(view, renderer.domElement); controls.enableDamping=true;
    const geom=new THREE.BufferGeometry();
    const mat=new THREE.PointsMaterial({size:2, sizeAttenuation:false, vertexColors:true});
    scene.add(new THREE.Points(geom, mat));
    Object.assign(this,{renderer,scene,view,controls,geom,mat});

    card.querySelector('.ps').oninput=e=>mat.size=+e.target.value;
    card.querySelector('.dl').onclick=()=>this.download();
    this._resize=()=>{ const w=canvas.clientWidth,h=canvas.clientHeight;
      renderer.setSize(w,h,false); view.aspect=w/h; view.updateProjectionMatrix(); };
    addEventListener('resize', this._resize);
    this.poll=setInterval(()=>this.tick(), 1000/HZ);
    this._resize();
    const loop=()=>{ if(!this.alive) return; requestAnimationFrame(loop);
      controls.update(); renderer.render(scene,view); };
    loop();
  }
  async tick(){
    try{ const buf=await (await fetch('depth/'+this.cam.id+'?t='+Date.now())).arrayBuffer();
         this.build(new Uint16Array(buf)); }catch(_){}
  }
  build(d){
    const c=this.cam, W=c.width, H=c.height, fx=c.fx, fy=c.fy, cx=c.cx, cy=c.cy;
    const near=c.near, far=Math.max(c.far, near+0.01), span=far-near;
    const maxN=Math.ceil(W/STRIDE)*Math.ceil(H/STRIDE);
    const pos=new Float32Array(maxN*3), col=new Float32Array(maxN*3);
    const opt=new Float32Array(maxN*3), rgb=new Uint8Array(maxN*3);
    let n=0;
    for(let v=0; v<H; v+=STRIDE){
      for(let u=0; u<W; u+=STRIDE){
        const mm=d[v*W+u]; if(!mm) continue;
        const R=mm/1000, dx=(u-cx)/fx, dy=(v-cy)/fy;
        const Z=R/Math.sqrt(1+dx*dx+dy*dy), X=dx*Z, Y=dy*Z;   // -> perpendicular depth
        opt[n*3]=X; opt[n*3+1]=Y; opt[n*3+2]=Z;               // optical frame (for .ply)
        pos[n*3]=X; pos[n*3+1]=-Y; pos[n*3+2]=-Z;             // display: y up, look -z
        let t=(R-near)/span; t=t<0?0:t>1?1:t;
        const cc=hsv((1-t)*240);
        col[n*3]=cc[0]/255; col[n*3+1]=cc[1]/255; col[n*3+2]=cc[2]/255;
        rgb[n*3]=cc[0]; rgb[n*3+1]=cc[1]; rgb[n*3+2]=cc[2]; n++;
      }
    }
    this.geom.setAttribute('position', new THREE.BufferAttribute(pos.subarray(0,n*3),3));
    this.geom.setAttribute('color',    new THREE.BufferAttribute(col.subarray(0,n*3),3));
    this.opt=opt; this.rgb=rgb; this.n=n;
    this.info.textContent = n.toLocaleString()+' points';
    if(this.needFrame && n>0){
      this.geom.computeBoundingSphere(); const s=this.geom.boundingSphere;
      this.controls.target.copy(s.center);
      this.view.position.set(s.center.x, s.center.y, s.center.z + Math.max(s.radius*2.2, 0.5));
      this.controls.update(); this.needFrame=false;
    }
  }
  download(){
    if(!this.n) return; const n=this.n, o=this.opt, g=this.rgb;
    const head='ply\\nformat ascii 1.0\\nelement vertex '+n+
      '\\nproperty float x\\nproperty float y\\nproperty float z'+
      '\\nproperty uchar red\\nproperty uchar green\\nproperty uchar blue\\nend_header\\n';
    const rows=new Array(n);
    for(let i=0;i<n;i++) rows[i]=o[i*3].toFixed(4)+' '+o[i*3+1].toFixed(4)+' '+o[i*3+2].toFixed(4)+
      ' '+g[i*3]+' '+g[i*3+1]+' '+g[i*3+2];
    const blob=new Blob([head+rows.join('\\n')+'\\n'], {type:'application/octet-stream'});
    const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
    a.download=this.cam.id+'.ply'; a.click(); URL.revokeObjectURL(a.href);
  }
  destroy(){ this.alive=false; clearInterval(this.poll);
    removeEventListener('resize', this._resize); this.renderer.dispose(); this.dom.remove(); }
}

function sync(){
  const want=new Set([...pick.querySelectorAll('input:checked')].map(i=>i.value));
  for(const [id,card] of cards) if(!want.has(id)){ card.destroy(); cards.delete(id); }
  for(const id of want) if(!cards.has(id)){ cards.set(id, new PclCard(CAMS.find(c=>c.id===id))); }
}
(async function init(){
  CAMS = await (await fetch('cameras.json')).json();
  CAMS.forEach((c,i)=>{
    const lab=document.createElement('label');
    const cb=document.createElement('input'); cb.type='checkbox'; cb.value=c.id; cb.checked=(i===0);
    cb.onchange=sync; lab.append(cb, document.createTextNode(' '+c.label)); pick.append(lab);
  });
  sync();
})();
</script>
</body></html>"""


class _WebViewer:
    """Serve a live, colour-mapped depth preview of every camera over localhost."""

    def __init__(self, units: list):
        import threading, json
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import numpy as np
        import omni.replicator.core as rep

        self._np = np
        self._lock = threading.Lock()
        self._frames = {}            # cam_id -> latest uint16-LE depth bytes
        self._cams = []              # [{id,label,width,height,near,far,annot}]
        self._last_pull = 0.0
        self._sub = None
        self._httpd = None

        # One render product + depth annotator per camera (capped resolution).
        for unit in units:
            for key, cam in unit["cams"].items():
                p = cam["params"]
                scale = min(1.0, WEB_VIEWER_MAX_W / float(p["width"]))
                vw, vh = max(1, int(p["width"] * scale)), max(1, int(p["height"] * scale))
                try:
                    rp = rep.create.render_product(cam["path"], (vw, vh))
                    annot = rep.AnnotatorRegistry.get_annotator("distance_to_camera")
                    annot.attach(rp)
                except Exception as exc:
                    print(f"  [web] annotator failed for {cam['path']}: {exc}")
                    continue
                self._cams.append(dict(
                    id=f"{unit['unit_id']}_{key}", label=f"{unit['unit_id']}  {key}",
                    width=vw, height=vh, near=p["near_m"], far=p["far_m"],
                    # intrinsics scaled to the (capped) preview resolution, so the
                    # browser can back-project depth into a metric point cloud
                    fx=p["fx"] * scale, fy=p["fy"] * scale,
                    cx=p["cx"] * scale, cy=p["cy"] * scale, annot=annot))

        if not self._cams:
            raise RuntimeError("no camera annotators could be created")

        meta = [{k: c[k] for k in ("id", "label", "width", "height",
                                   "near", "far", "fx", "fy", "cx", "cy")}
                for c in self._cams]
        html = _WEB_VIEWER_HTML.replace("__HZ__", str(int(WEB_VIEWER_HZ)))
        viewer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):       # silence per-request logging
                pass

            def _send(self, code, ctype, body: bytes):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    self._send(200, "text/html; charset=utf-8", html.encode())
                elif path == "/cameras.json":
                    self._send(200, "application/json", json.dumps(meta).encode())
                elif path.startswith("/depth/"):
                    cam_id = path[len("/depth/"):]
                    with viewer._lock:
                        buf = viewer._frames.get(cam_id)
                    if buf is None:
                        self._send(503, "text/plain", b"warming up")
                    else:
                        self._send(200, "application/octet-stream", buf)
                else:
                    self._send(404, "text/plain", b"not found")

        self._httpd = ThreadingHTTPServer(("127.0.0.1", WEB_VIEWER_PORT), Handler)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        self._sub = omni.kit.app.get_app().get_update_event_stream() \
            .create_subscription_to_pop(self._on_update, name="ros2_itof_webviewer")
        print(f"[web] depth viewer at http://localhost:{WEB_VIEWER_PORT}/   "
              f"({len(self._cams)} camera(s))")

    def _on_update(self, _):
        import time
        now = time.monotonic()
        if now - self._last_pull < 1.0 / max(1, WEB_VIEWER_HZ):
            return
        self._last_pull = now
        np = self._np
        for cam in self._cams:
            try:
                data = cam["annot"].get_data()
            except Exception:
                continue
            arr = np.asarray(data, dtype=np.float32)
            if arr.size == 0:
                continue
            mm = arr.copy()
            mm[~np.isfinite(mm)] = 0.0          # inf/nan -> "no return"
            mm = np.clip(mm * 1000.0, 0, 65535).astype("<u2")
            with self._lock:
                self._frames[cam["id"]] = mm.tobytes()

    def destroy(self):
        if self._sub is not None:
            self._sub = None
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
        for cam in self._cams:
            try:
                cam["annot"].detach()
            except Exception:
                pass
        self._cams = []


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    """Discover every DepthVista unit and build all ROS 2 publisher graphs."""
    print("\n" + "═" * 72)
    print("  isaac_usd_ros_itof.py  —  e-con DepthVista Helix iToF")
    print("  cameras auto-detected (GMSL / USB / unsuffixed) | Sensor: onsemi AF0130")
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
    multi = len(roots) > 1            # only number cameras when there is more than one
    for index, (root, type_tag) in enumerate(roots):
        base      = f"cam{index}" if multi else "cam"
        unit_id   = f"{base}_{type_tag}" if type_tag else base
        ns_prefix = f"{TOPIC_ROOT}/{unit_id}"
        graph_tag = unit_id.upper()
        # With multiple cameras, group each one's graphs under /Graphs/<unit_id>;
        # a single camera keeps its graphs flat under /Graphs.
        graph_root = f"{GRAPH_ROOT}/{unit_id}" if multi else GRAPH_ROOT

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
                graph_path = f"{graph_root}/ROS2Camera_{graph_tag}_{key.upper()}",
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
            graph_root = graph_root,
            imu_graph  = f"{graph_root}/ROS2ImuGraph_{graph_tag}",
            imu_print  = _imu_print_enabled(index),
        ))
        print(f"  unit[{index}] {unit_id}   {root}   IMU: {imu_prim or 'NOT FOUND'}")

    # ── STEP 4 — Bake intrinsics (optional) ──────────────────────────────────
    if BAKE_INTRINSICS:
        print("\n[STEP 4] Baking intrinsics …")
        for unit in units:
            for cam in unit["cams"].values():
                _bake_intrinsics(stage, cam["path"], cam["params"])
        await _wait(5)
    else:
        print("\n[STEP 4] Baking intrinsics … SKIPPED (streaming camera as authored)")

    # ── STEP 5 — Verify IMU sensors ──────────────────────────────────────────
    print("\n[STEP 5] Verifying IMU sensors …")
    for unit in units:
        unit["imu_ok"] = bool(unit["imu_prim"]) and _verify_imu_sensor(unit["imu_prim"])

    # ── STEP 6 — Shared graph (/clock + /tf) ─────────────────────────────────
    print("\n[STEP 6] Shared graph …")
    _ensure_graph_root(stage)
    for unit in units:                       # per-camera subfolders (multi-camera only)
        _ensure_scope(stage, unit["graph_root"])
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

    # ── STEP 10 — Web viewer (optional) ──────────────────────────────────────
    global _web_viewer
    if WEB_VIEWER:
        print("\n[STEP 10] Web viewer …")
        try:
            _web_viewer = _WebViewer(units)
        except Exception as exc:
            print(f"  [web] viewer disabled: {exc}")
            _web_viewer = None

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
    print(f"  {GRAPH_ROOT}/ROS2SharedGraph  ->  /clock  /tf   "
          f"(all unit frames -> {TF_WORLD_FRAME})")
    print()
    print("  RViz depth: Normalize=OFF  highres 0.2-2.0 | longrange 0.5-6.0")
    if WEB_VIEWER and _web_viewer is not None:
        print(f"  Web viewer: http://localhost:{WEB_VIEWER_PORT}/  (live depth, no RViz needed)")
    print("  Stop: Ctrl+Alt+R (viewport focused) or teardown()")
    print("═" * 72 + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# TEARDOWN
# ══════════════════════════════════════════════════════════════════════════════

def teardown():
    """Stop publishing: drop the hotkey, remove all ROS2 graphs, and (if
    ``STOP_SIM_ON_EXIT``) stop the timeline.  Safe to call repeatedly.
    """
    global _hotkey_watcher, _web_viewer
    if _hotkey_watcher is not None:
        _hotkey_watcher.destroy()
        _hotkey_watcher = None
    if _web_viewer is not None:
        _web_viewer.destroy()
        _web_viewer = None

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
