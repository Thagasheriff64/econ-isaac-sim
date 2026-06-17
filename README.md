# e-con DepthVista Helix iToF — Isaac Sim

This extension integrates the **e-con DepthVista Helix iToF** camera into NVIDIA Isaac Sim. Once
installed, the camera is available directly from Isaac Sim's **Create** menu and can be added to
any scene in a few clicks. An optional ROS 2 publisher and a browser-based depth viewer are
included for streaming and inspecting the camera's data.

## Requirements

- **NVIDIA Isaac Sim ≥ 5.1.0** — see the
  [Isaac Sim installation guide](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_workstation.html).
  Tested on 5.1.0 and 6.0.0.
- **git** and **python3** (`python` on Windows). `git` clones the repository; `python3` runs the
  installer that registers the extension in Isaac Sim's `.kit` files.

## Installation

**Linux**
```bash
git clone https://github.com/Thagasheriff64/econ-isaac-sim.git
cd econ-isaac-sim
./build.sh
```

**Windows**
```bat
git clone https://github.com/Thagasheriff64/econ-isaac-sim.git
cd econ-isaac-sim
build.bat
```

Notes on what the installer does:

- It locates Isaac Sim automatically. If it cannot, it prompts you for the Isaac Sim folder (the
  one containing `isaac-sim.sh` / `isaac-sim.bat`).
- It **copies** the extension — including its USD assets — into Isaac Sim's `extsUser` folder. The
  installed camera is therefore self-contained: you may move or delete this cloned repository
  afterwards and Isaac Sim will continue to work.
- Once installed, the camera loads automatically on every launch.

To remove the camera, use the [uninstaller](#uninstallation) rather than deleting files by hand,
so that the registration in Isaac Sim's `.kit` files is also reverted.

## Usage

1. If Isaac Sim is already running, close and relaunch it.
2. Open **Create → Sensors → Camera and Depth Sensors → e-con**.
3. Select **DepthVista Helix iToF**. The camera is added to your scene under `/World`.

![Create menu showing DepthVista Helix iToF under e-con](docs/images/01-create-menu-depthvista.png)

## Camera variants

Two USD variants of the camera are included in
[`exts/econ.itof.menu/assets/`](exts/econ.itof.menu/assets):

| File | Connector |
|------|-----------|
| `DEPTHVISTA_HELIX_GMSL.usd` | GMSL |
| `DEPTHVISTA_HELIX_USB.usd`  | USB |

- The Create menu exposes a single entry — **DepthVista Helix iToF** (the GMSL variant).
- To use the USB variant, reference
  [`DEPTHVISTA_HELIX_USB.usd`](exts/econ.itof.menu/assets/DEPTHVISTA_HELIX_USB.usd) into your stage
  directly.
- When added, the camera is placed under the stage's default prim (`/World`) with its full sensor
  hierarchy intact.

![Stage hierarchy of the added camera](docs/images/02-stage-hierarchy.png)

## ROS 2 streaming (optional)

[`ros2/isaac_usd_ros_itof.py`](ros2/isaac_usd_ros_itof.py) turns every DepthVista camera in the
stage into a live ROS 2 publisher. Key behaviour:

- **Automatic detection.** All DepthVista cameras in the stage are found automatically; the script
  takes no arguments.
- **Naming.** A single camera is named `cam`. When more than one is present, they are numbered by
  discovery order (`cam0`, `cam1`, …). A camera loaded from the explicit GMSL or USB variant also
  carries its connector type (`cam_gmsl`, `cam0_usb`, …).
- **Scales to any count.** Add as many cameras as you need; the script generates a matching set of
  topics and graphs for every camera it finds.

> **No external ROS 2 installation is required to publish.** The script uses the **ROS 2 Humble**
> libraries bundled with Isaac Sim (the `isaacsim.ros2.bridge` extension), so a system ROS 2
> installation or a sourced workspace is not needed on the simulation side. ROS 2 Humble is only
> required on the consumer side — for example, to run RViz or `ros2 topic echo`.

Each camera publishes under the namespace `<ns> = /tof/cam`. A `{i}` index is appended only when
more than one camera is present, plus a `_{type}` suffix for the explicit GMSL/USB variants:

| Topic | Stream | Resolution | Range |
|-------|--------|-----------|-------|
| `<ns>/highres/{depth, camera_info, points}`   | High-resolution depth and point cloud | 1280×960 | 0.2–2.0 m |
| `<ns>/longrange/{depth, camera_info, points}` | Long-range depth and point cloud | 640×480 | 0.5–6.0 m |
| `<ns>/imu` | 6-axis IMU | — | 416 Hz |
| `/clock`, `/tf` | Shared clock and transform tree | — | Published once |

`highres` and `longrange` are two configurations of the same physical module; they therefore
share a single IMU and a single TF frame per camera. Every camera frame is a child of `world`.

### Running the script from the Script Editor

1. Add a camera to the scene (see [Usage](#usage)) and press **Play** in the toolbar.
2. Open the Script Editor via **Window → Script Editor**.

   ![Window menu with Script Editor highlighted](docs/images/03-window-script-editor.png)

3. In the Script Editor, choose **File → Open**.

   ![Script Editor File menu showing Open](docs/images/04-script-editor-open.png)

4. Browse to your cloned repository and select `econ-isaac-sim/ros2/isaac_usd_ros_itof.py`. The
   script loads into a new tab.

   ![Script loaded in the Script Editor](docs/images/05-script-editor-loaded.png)

5. Run the script by clicking **Run** or pressing **Ctrl+Enter**.

The script builds OmniGraph action graphs in the stage, all nested under a single `Graphs` scope.
In the names below, `<UNIT>` is the upper-cased camera name (`CAM`, `CAM0`, `CAM0_GMSL`, …). The
following graphs are generated:

- **`ROS2SharedGraph`** — publishes the shared `/clock` and `/tf` (Publish Clock and Publish
  Transform Tree), driven by the simulation clock.

  ![ROS2SharedGraph with clock and TF nodes](docs/images/06-ros2-shared-graph.png)

- **`ROS2Camera_<UNIT>_HIGHRES`** — the 1280×960 render product feeding the depth, camera_info,
  and point-cloud publishers for that camera.

  ![High-resolution camera graph](docs/images/07-ros2-camera-highres-graph.png)

- **`ROS2Camera_<UNIT>_LONGRANGE`** — the 640×480 render product, with the same set of publishers.

  ![Long-range camera graph](docs/images/08-ros2-camera-longrange-graph.png)

- **`ROS2ImuGraph_<UNIT>`** — reads the IMU and publishes it (Publish IMU), with an optional
  on-screen readout of angular velocity and linear acceleration.

  ![IMU graph](docs/images/09-ros2-imu-graph.png)

One graph set is generated per camera, so adding more cameras produces correspondingly named
topics and graphs. Set `ROS2_DOMAIN_ID` near the top of the script to match the `ROS_DOMAIN_ID` in
your shell.

### Viewing in RViz

In RViz (ROS 2 Humble):

- Set the **Fixed Frame** to **`world`**. Every camera's TF frame is a child of `world`, so all
  cameras share this common frame.
- To rename the common frame, change `TF_WORLD_FRAME` near the top of the script.
- To parent all frames under another prim (for example, a robot base), set `TF_PARENT_PRIM` to
  that prim's path.

### Browser depth viewer (optional, no RViz required)

To inspect depth in a browser instead of RViz, set `WEB_VIEWER = True` near the top of the script.
Alongside the ROS 2 publishers, the script then serves a page at `http://localhost:8211/`.

- **Depth tiles.** Each camera's live depth is shown, colour-mapped over the camera's near/far
  range. Each tile reports the metric distance at a probe point — the cursor while hovering the
  image, otherwise the last point clicked, otherwise the image centre. The raw metric depth is
  sent to the browser, so the colouring and the readout are computed client-side and update in
  real time.
- **Point clouds.** A point-clouds section lists every camera as a checkbox. Tick one or more to
  render each as its own interactive 3D point cloud, coloured by distance — drag to rotate, scroll
  to zoom, right-drag to pan. Use **Download .ply** on any cloud to export it. Points are
  back-projected from depth in the browser using each camera's intrinsics.
- **Settings** (top of the script): `WEB_VIEWER`, `WEB_VIEWER_PORT`, `WEB_VIEWER_HZ`, and
  `WEB_VIEWER_MAX_W` (preview width cap).

The viewer runs alongside ROS 2 and does not replace it. The 3D view loads three.js from a CDN, so
the browser needs internet access; the 2D depth tiles work offline.

![Browser viewer: per-camera depth tiles and an interactive point cloud](docs/images/10-web-viewer.png)

To stop or restart streaming:

- **Stop** — press `Ctrl+Alt+R` with the Isaac Sim viewport focused, or call `teardown()`.
- **Restart** — run the file again; stale graphs, the hotkey, and the viewer reset automatically.

## Uninstallation

A single command reverts every change and restores Isaac Sim to its original state:

```bash
./uninstall.sh          # Linux
uninstall.bat           # Windows
```

It locates Isaac Sim the same way the installer does, restores the `.kit` files, and removes the
extension.

## Notes

- Re-run the installer after reinstalling or updating Isaac Sim.
