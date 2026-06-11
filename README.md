# e-con DepthVista Helix iToF — Isaac Sim

Adds the **e-con DepthVista Helix iToF** camera to NVIDIA Isaac Sim. After a one-time install,
it appears in the viewport menu under
**Create → Sensors → Camera and Depth Sensors → e-con**, alongside the other camera vendors.

![Create menu — DepthVista Helix iToF under e-con](docs/images/01-create-menu-depthvista.png)

### Variants — what ships vs. what shows

Two USD builds of the camera live in [`exts/econ.itof.menu/assets/`](exts/econ.itof.menu/assets):

| File | Connector |
|------|-----------|
| `DEPTH_VISTA_HELIX_GMSL.usd` | GMSL |
| `DEPTH_VISTA_HELIX_USB.usd`  | USB |

The two are visually identical, so to keep the menu clean **Isaac Sim exposes only one entry —
`DepthVista Helix iToF`** (the GMSL build), with no variant suffix. **Both USDs remain available
in the repo / on GitHub** — if you specifically need the USB build, download it from
[`exts/econ.itof.menu/assets/DEPTH_VISTA_HELIX_USB.usd`](exts/econ.itof.menu/assets/DEPTH_VISTA_HELIX_USB.usd)
and reference it into your stage directly.

When added, the camera lands under the stage's default prim (`/World`) at true scale
(~95 × 37 × 39 mm) with its full sensor hierarchy:

![Stage hierarchy of the added camera](docs/images/02-stage-hierarchy.png)

## Requirements
- NVIDIA **Isaac Sim 5.1** installed
- **git** and **python3** (python on Windows)

## Install

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

The installer finds Isaac Sim automatically. If it can't, it asks you to type the Isaac Sim
folder (the one containing `isaac-sim.sh` / `isaac-sim.bat`). That's the whole setup — the camera
is now built into Isaac Sim and loads on every launch.

## Use
1. If Isaac Sim is open, close and reopen it. Launch it normally.
2. **Create → Sensors → Camera and Depth Sensors → e-con**
3. Pick **DepthVista Helix iToF** — the camera drops into your scene at `/World`.

## ROS 2 streaming (optional)

[`ros2/isaac_usd_ros_itof.py`](ros2/isaac_usd_ros_itof.py) turns every DepthVista unit in the
stage into a live ROS 2 publisher. It **auto-detects** all camera units (GMSL and USB) — no
arguments — numbering them by discovery order and tagging each with its real type
(`cam0_gmsl`, `cam1_usb`, …).

Each unit publishes under `<ns> = /tof/cam{i}_{type}`:

| Topic | Stream | Resolution | Range |
|-------|--------|-----------|-------|
| `<ns>/highres/{depth, camera_info, points}`   | high-res depth + point cloud | 1280×960 | 0.2–2.0 m |
| `<ns>/longrange/{depth, camera_info, points}` | long-range depth + point cloud | 640×480 | 0.5–6.0 m |
| `<ns>/imu` | 6-axis IMU | — | 416 Hz |
| `/clock`, `/tf` | shared clock + transform tree | — | once |

`highres` and `longrange` are the same physical module, so they share one IMU and one TF frame
per unit; every unit frame is a child of `world`.

### Running it from the Script Editor

1. Add a camera to the scene (see **Use** above) and press **Play** in the toolbar.
2. Open the Script Editor: **Window → Script Editor**.

   ![Window menu → Script Editor](docs/images/03-window-script-editor.png)

3. In the Script Editor, **File → Open**.

   ![Script Editor → File → Open](docs/images/04-script-editor-open.png)

4. Browse to your cloned repo and pick `econ-isaac-sim/ros2/isaac_usd_ros_itof.py`. The script
   loads into a new tab.

   ![Script loaded in the editor](docs/images/05-script-editor-loaded.png)

5. **Run** it — click **Run** or press **Ctrl+Enter**.

The script builds OmniGraph action graphs in the stage that drive the ROS 2 topics. You'll see:

- **`ROS2SharedGraph`** — the shared `/clock` and `/tf` (Publish Transform Tree + Publish Clock),
  driven by the simulation clock:

  ![ROS2SharedGraph — clock and TF](docs/images/06-ros2-shared-graph.png)

- **`ROS2Camera_CAM<i>_<TYPE>_HIGHRES`** — the 1280×960 render product feeding depth,
  camera_info and point-cloud publishers for that unit:

  ![High-res camera graph](docs/images/07-ros2-camera-highres-graph.png)

- **`ROS2Camera_CAM<i>_<TYPE>_LONGRANGE`** — the 640×480 render product, same publisher set:

  ![Long-range camera graph](docs/images/08-ros2-camera-longrange-graph.png)

- **`ROS2ImuGraph_CAM<i>_<TYPE>`** — the IMU read → Publish IMU, with an optional on-screen
  readout of angular velocity / linear acceleration:

  ![IMU graph](docs/images/09-ros2-imu-graph.png)

One graph set is generated **per camera per variant** found in the stage, so adding more units
produces correspondingly numbered topics. Set `ROS2_DOMAIN_ID` near the top of the script to
match your shell's `ROS_DOMAIN_ID`.

**Stop:** `Ctrl+Alt+R` (Isaac viewport focused) or call `teardown()`. **Re-run:** execute the
file again — stale graphs and the hotkey auto-reset.

## Uninstall
One command — reverts every change and returns Isaac Sim to stock:
```bash
./uninstall.sh          # Linux
uninstall.bat           # Windows
```
(It finds Isaac Sim the same way the installer does, restores the `.kit` files, and removes the
extension.)

## Notes
- Re-run the installer after **reinstalling or updating Isaac Sim**.
