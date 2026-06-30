# e-con DepthVista Helix iToF — Isaac Sim

Adds the **e-con DepthVista Helix iToF** camera to Isaac Sim's supported camera and depth sensors,
with an optional ROS 2 publisher and a browser depth viewer.

## Requirements

- **NVIDIA Isaac Sim ≥ 5.1.0** — refer to the
  [installation guide](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_workstation.html).
  Tested on 5.1.0 and 6.0.0, on both Windows and Linux.

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

- Auto-detects Isaac Sim (prompts for the folder if not found).
- Copies the extension and assets into `extsUser` inside the Isaac Sim folder — it is self-contained, so the
  cloned repository can be deleted afterwards — and auto-loads on every launch.
- Remove it with the [uninstaller](#uninstallation), not by deleting files manually.

If you have multiple Isaac Sim versions installed, or already know the path, set `ISAACSIM_PATH`
to skip auto-detection and target a specific install:

```bash
ISAACSIM_PATH=/home/econsy/ROBOTICS/downloads/isaacsim ./build.sh        # Linux
```
```bat
set ISAACSIM_PATH=C:\path\to\isaacsim & build.bat                       :: Windows
```

## Usage

1. Relaunch Isaac Sim if it is already running.
2. Open **Create → Sensors → Camera and Depth Sensors → e-con**.
3. Select **DepthVista Helix iToF** — added under `/World`.

![Create menu showing DepthVista Helix iToF under e-con](docs/images/01-create-menu-depthvista.png)

## Camera variants

| File | Connector |
|------|-----------|
| `DEPTHVISTA_HELIX_GMSL.usd` | GMSL |
| `DEPTHVISTA_HELIX_USB.usd`  | USB |

- The menu exposes a single entry — **DepthVista Helix iToF** (the GMSL variant).
- For the USB variant, reference
  [`DEPTHVISTA_HELIX_USB.usd`](exts/econ.itof.menu/assets/DEPTHVISTA_HELIX_USB.usd) into your stage
  directly.

![Stage hierarchy of the added camera](docs/images/02-stage-hierarchy.png)

## ROS 2 streaming (optional)

[`ros2/isaac_usd_ros_itof.py`](ros2/isaac_usd_ros_itof.py) publishes every DepthVista camera in
the stage.

- **Detection** — all cameras found automatically; no arguments.
- **Naming** — `cam`; `cam0`, `cam1`, … when more than one; `_gmsl` / `_usb` suffix for explicit
  variants.
- **Scales** — generates the topics and OmniGraph sets for each camera automatically.

> Uses the **ROS 2 Humble** libraries bundled with Isaac Sim (`isaacsim.ros2.bridge`) — no system
> ROS 2 is needed to publish. ROS 2 Humble is required only on the consumer side (RViz,
> `ros2 topic echo`).

Namespace `<ns> = /tof/cam` (a `{i}` index is added only when more than one camera is present,
plus a `_{type}` suffix for the GMSL/USB variants):

| Topic | Stream | Resolution | Range |
|-------|--------|-----------|-------|
| `<ns>/highres/{depth, camera_info, points}`   | High-resolution depth and point cloud | 1280×960 | 0.2–2.0 m |
| `<ns>/longrange/{depth, camera_info, points}` | Long-range depth and point cloud | 640×480 | 0.5–6.0 m |
| `<ns>/imu` | 6-axis IMU | — | 416 Hz |
| `/clock`, `/tf` | Shared clock and transform tree | — | Published once |

`highres` and `longrange` are two configurations of the same module, so they share one IMU and one
TF frame per camera (a child of `world`).

### Running from the Script Editor

1. Add a camera (see [Usage](#usage)) and press **Play**.
2. Open **Window → Script Editor**.

   ![Window menu with Script Editor highlighted](docs/images/03-window-script-editor.png)

3. Choose **File → Open**.

   ![Script Editor File menu showing Open](docs/images/04-script-editor-open.png)

4. Select `econ-isaac-sim/ros2/isaac_usd_ros_itof.py`.

   ![Script loaded in the Script Editor](docs/images/05-script-editor-loaded.png)

5. **Run** (or press **Ctrl+Enter**).

The OmniGraph action graphs are created under a single `Graphs` scope. With more than one camera,
each camera's graphs are grouped in a `/Graphs/<camera>` subfolder (e.g. `/Graphs/cam0`). Below,
`<UNIT>` is the upper-cased camera name (e.g. `CAM`, `CAM0_GMSL`):

![Per-camera graph grouping under the Graphs scope (multiple cameras)](docs/images/06-graphs-grouped.png)

- **`ROS2SharedGraph`** — shared `/clock` and `/tf`.

  ![ROS2SharedGraph with clock and TF nodes](docs/images/07-ros2-shared-graph.png)

- **`ROS2Camera_<UNIT>_HIGHRES`** — 1280×960 depth, camera_info, points.

  ![High-resolution camera graph](docs/images/08-ros2-camera-highres-graph.png)

- **`ROS2Camera_<UNIT>_LONGRANGE`** — 640×480, same publishers.

  ![Long-range camera graph](docs/images/09-ros2-camera-longrange-graph.png)

- **`ROS2ImuGraph_<UNIT>`** — reads and publishes the IMU, with an optional on-screen readout of
  linear acceleration / angular velocity. Three settings control it:
  - `IMU_PRINT_CAMERAS` — which cameras show the readout.
  - `IMU_LINEAR_TO_SCREEN` — overlay linear acceleration.
  - `IMU_ANGULAR_TO_SCREEN` — overlay angular velocity.
  - Keep it to a single camera (default: `cam` / `cam0`) — more than one is unreadable on screen.

  ![IMU graph](docs/images/10-ros2-imu-graph.png)

Set `ROS2_DOMAIN_ID` (top of the script) to match your shell's `ROS_DOMAIN_ID`.

### Viewing in RViz

- Set the **Fixed Frame** to **`world`** (all camera frames are children of it).
- Rename it via `TF_WORLD_FRAME`; parent all frames under a prim via `TF_PARENT_PRIM`.

All cameras share the `world` frame, so their point clouds line up in a single view:

![Point clouds from all cameras fused in the world frame in RViz](docs/images/11-rviz-viewer.png)

### Browser depth viewer (optional, no RViz)

The browser viewer is enabled by default (`WEB_VIEWER = True` in
[`ros2/isaac_usd_ros_itof.py`](ros2/isaac_usd_ros_itof.py)) and served at `http://localhost:8211/`,
alongside ROS 2. Set it to `False` to disable.

> Refer to the script to set the other options as well.

- **Depth tiles** — live depth, colour-mapped by distance; a probe (cursor → last click → centre)
  reads the metric distance.
- **Point clouds** — per-camera checkboxes; interactive 3D (rotate / zoom / pan) with
  **Download .ply**.
- **Settings** — `WEB_VIEWER`, `WEB_VIEWER_PORT`, `WEB_VIEWER_HZ`, and `WEB_VIEWER_MAX_W`
  (`None` = the camera's full resolution; set e.g. `640` to cap the preview width).

The 3D view loads three.js from a CDN (needs internet); the 2D tiles work offline.

![Browser viewer: per-camera depth tiles and an interactive point cloud](docs/images/13-web-viewer.png)

- **Stop** — `Ctrl+Alt+R` (viewport focused) or `teardown()`.
- **Restart** — run the file again; graphs, hotkey, and viewer reset automatically.

## Examples

- [**UR10 Palletizing**](examples/example1/README.md) — add two DepthVista cameras (wrist
  and over-pallet) and a camera stand to Isaac Sim's UR10 Palletizing example,
  then stream to ROS 2 and the browser viewer.
- [**Nova Carter navigation**](examples/example2/README.md) — mount four
  DepthVista cameras (front/back/left/right) on a Nova Carter, stream to ROS 2 under
  the robot's TF tree, and navigate with the Nav2 `carter_navigation` package.

## Uninstallation

```bash
./uninstall.sh          # Linux
uninstall.bat           # Windows
```

Restores the `.kit` files and removes the extension. To target a specific install (multiple Isaac
Sim versions, or a known path), set `ISAACSIM_PATH` as with the installer:

```bash
ISAACSIM_PATH=/home/econsy/ROBOTICS/downloads/isaacsim ./uninstall.sh    # Linux
```
```bat
set ISAACSIM_PATH=C:\path\to\isaacsim & uninstall.bat                   :: Windows
```

## Notes

- Re-run the installer after reinstalling or updating Isaac Sim.
