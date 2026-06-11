# e-con DepthVista Helix iToF — Isaac Sim

This extension integrates the **e-con DepthVista Helix iToF** camera into NVIDIA Isaac Sim. Once
installed, the camera is available directly from Isaac Sim's **Create** menu, alongside the other
camera vendors, and can be added to any scene in a few clicks.

## Requirements

- NVIDIA **Isaac Sim 5.1**
- **git** and **python3** (`python` on Windows)

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

The installer locates Isaac Sim automatically. If it cannot, it prompts you for the Isaac Sim
folder (the one containing `isaac-sim.sh` / `isaac-sim.bat`). That completes the setup: the camera
is now built into Isaac Sim and loads on every launch.

## Usage

1. If Isaac Sim is already running, close and relaunch it.
2. Open **Create → Sensors → Camera and Depth Sensors → e-con**.
3. Select **DepthVista Helix iToF**. The camera is added to your scene under `/World`.

![Create menu showing DepthVista Helix iToF under e-con](docs/images/01-create-menu-depthvista.png)

## Camera variants

Two USD builds of the camera are included in
[`exts/econ.itof.menu/assets/`](exts/econ.itof.menu/assets):

| File | Connector |
|------|-----------|
| `DEPTH_VISTA_HELIX_GMSL.usd` | GMSL |
| `DEPTH_VISTA_HELIX_USB.usd`  | USB |

Isaac Sim shows a single entry — **DepthVista Helix iToF** (the GMSL build). If you need the USB
build, reference
[`DEPTH_VISTA_HELIX_USB.usd`](exts/econ.itof.menu/assets/DEPTH_VISTA_HELIX_USB.usd) into your
stage directly.

When added, the camera is placed under the stage's default prim (`/World`) with its full sensor
hierarchy intact.

![Stage hierarchy of the added camera](docs/images/02-stage-hierarchy.png)

## ROS 2 streaming (optional)

[`ros2/isaac_usd_ros_itof.py`](ros2/isaac_usd_ros_itof.py) turns every DepthVista unit in the
stage into a live ROS 2 publisher. It automatically detects all camera units (GMSL and USB),
requires no arguments, and numbers them by discovery order, tagging each with its connector type
(`cam0_gmsl`, `cam1_usb`, and so on). You can add as many cameras as you need; the script
generates a matching set of topics and graphs for every unit it finds in the stage.

> **No external ROS installation is required to publish.** The script uses the **ROS 2 Humble**
> libraries bundled with Isaac Sim (the `isaacsim.ros2.bridge` extension), so a system ROS
> installation or a sourced workspace is not needed on the simulation side. ROS 2 Humble is only
> required on the consumer side — for example, to run RViz or `ros2 topic echo`.

Each unit publishes under the namespace `<ns> = /tof/cam{i}_{type}`:

| Topic | Stream | Resolution | Range |
|-------|--------|-----------|-------|
| `<ns>/highres/{depth, camera_info, points}`   | High-resolution depth and point cloud | 1280×960 | 0.2–2.0 m |
| `<ns>/longrange/{depth, camera_info, points}` | Long-range depth and point cloud | 640×480 | 0.5–6.0 m |
| `<ns>/imu` | 6-axis IMU | — | 416 Hz |
| `/clock`, `/tf` | Shared clock and transform tree | — | Published once |

The `highres` and `longrange` streams come from the same physical module, so they share one IMU
and one TF frame per unit. Every unit frame is a child of `world`.

### Running the script from the Script Editor

1. Add a camera to the scene (see **Usage** above) and press **Play** in the toolbar.
2. Open the Script Editor via **Window → Script Editor**.

   ![Window menu with Script Editor highlighted](docs/images/03-window-script-editor.png)

3. In the Script Editor, choose **File → Open**.

   ![Script Editor File menu showing Open](docs/images/04-script-editor-open.png)

4. Browse to your cloned repository and select `econ-isaac-sim/ros2/isaac_usd_ros_itof.py`. The
   script loads into a new tab.

   ![Script loaded in the Script Editor](docs/images/05-script-editor-loaded.png)

5. Run the script by clicking **Run** or pressing **Ctrl+Enter**.

The script builds OmniGraph action graphs in the stage to drive the ROS 2 topics. The following
graphs are generated:

- **`ROS2SharedGraph`** — publishes the shared `/clock` and `/tf` (Publish Clock and Publish
  Transform Tree), driven by the simulation clock.

  ![ROS2SharedGraph with clock and TF nodes](docs/images/06-ros2-shared-graph.png)

- **`ROS2Camera_CAM<i>_<TYPE>_HIGHRES`** — the 1280×960 render product feeding the depth,
  camera_info, and point-cloud publishers for that unit.

  ![High-resolution camera graph](docs/images/07-ros2-camera-highres-graph.png)

- **`ROS2Camera_CAM<i>_<TYPE>_LONGRANGE`** — the 640×480 render product, with the same set of
  publishers.

  ![Long-range camera graph](docs/images/08-ros2-camera-longrange-graph.png)

- **`ROS2ImuGraph_CAM<i>_<TYPE>`** — reads the IMU and publishes it (Publish IMU), with an
  optional on-screen readout of angular velocity and linear acceleration.

  ![IMU graph](docs/images/09-ros2-imu-graph.png)

One graph set is generated per camera and per variant found in the stage, so adding more units
produces correspondingly numbered topics. Set `ROS2_DOMAIN_ID` near the top of the script to
match the `ROS_DOMAIN_ID` in your shell.

### Viewing in RViz

In RViz (ROS 2 Humble), set the **Fixed Frame** to **`world`**. Every camera's TF frame is a
child of `world`, so all units share this common frame. To rename it, change `TF_WORLD_FRAME` near
the top of the script. You can also set `TF_PARENT_PRIM` to a prim path (for example, a robot
base) to parent all frames under that prim.

**Stopping:** press `Ctrl+Alt+R` with the Isaac Sim viewport focused, or call `teardown()`.
**Re-running:** execute the file again — stale graphs and the hotkey reset automatically.

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
