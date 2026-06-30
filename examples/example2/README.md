# Example 2 — DepthVista cameras on a Nova Carter for navigation

A **Nova Carter** with four DepthVista Helix iToF cameras mounted on its exterior
(front / back / left / right), streaming ROS 2 depth and point clouds alongside the
robot's own sensors for Nav2.

### What it adds

Each camera is the menu's `DEPTHVISTA_HELIX_GMSL.usd`, parented under
`/World/Nova_Carter_ROS/chassis_link/sensors` at the e-con sensor height (~0.35 m),
facing outward:

| Side | Translate (robot frame, m) | Faces | Rotate Z |
|------|----------------------------|-------|----------|
| Front | (0.117, 0.000, 0.346) | +X | -90 |
| Back  | (-0.581, 0.000, 0.346) | -X | 90 |
| Left  | (-0.355, 0.167, 0.346) | +Y | 0 |
| Right | (-0.355, -0.167, 0.346) | -Y | 180 |

### Requirements

- The extension installed, so the DepthVista USD is available — see the
  [main README](../../README.md#installation).
- A Nova Carter scene loaded with the four cameras mounted under
  `chassis_link/sensors` (Create menu or a mount script).

### Run it

1. Load the Nova Carter warehouse scene with the four cameras in place.
2. Press **Play** and run
   [`isaac_usd_ros_itof_example2_nova_carter.py`](isaac_usd_ros_itof_example2_nova_carter.py)
   from the Script Editor. It auto-detects the units and publishes
   depth / points / camera_info / IMU.

This example script differs from the default
[`../../ros2/isaac_usd_ros_itof.py`](../../ros2/isaac_usd_ros_itof.py) in two ways:

- **TF parent** — frames are parented under the Carter's `base_link`
  (`TF_PARENT_PRIM = /World/Nova_Carter_ROS/chassis_link`, `TF_WORLD_FRAME = base_link`),
  so they join the robot's `map → odom → base_link` tree instead of a separate `world`.
- **Depth range** — `OVERRIDE_DEPTH_RANGE` forces the published ToF range to the
  DepthVista spec (highres 0.2–2.0 m, longrange 0.5–6.0 m), regardless of the
  camera's authored `isaac:depthRange`.

### Navigation (Nav2)

[`navigation/`](navigation) is a ROS 2 workspace whose
[`src/carter_navigation/`](navigation/src/carter_navigation) package (launch files,
maps, params, RViz configs) navigates the Carter in the warehouse / hospital / office
maps. Build and launch:

```bash
cd navigation && colcon build && source install/setup.bash
ros2 launch carter_navigation carter_navigation.launch.py
```
