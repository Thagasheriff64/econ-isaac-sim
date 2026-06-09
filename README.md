# e-con DepthVista Helix iToF — Isaac Sim

Adds the **e-con DepthVista Helix iToF** cameras to NVIDIA Isaac Sim. After a one-time install,
the cameras appear in the viewport menu under
**Create → Sensors → Camera and Depth Sensors → e-con**, just like the built-in Intel / Orbbec /
Stereolabs cameras.

Two models are included:
- **DepthVista Helix iToF (USB)**
- **DepthVista Helix iToF (GMSL)**

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
3. Pick **DepthVista Helix iToF (USB)** or **(GMSL)** — the camera drops into your scene.

## Uninstall
```bash
python3 scripts/patch_kit.py "<isaac-sim-folder>/apps" econ.itof.menu --uninstall
rm "<isaac-sim-folder>/extsUser/econ.itof.menu"        # Windows: delete the folder
```

## Notes
- Re-run the installer after **reinstalling or updating Isaac Sim**.
- `ros2/isaac_usd_ros_itof.py` is an optional ROS 2 streaming node: with a camera in the scene,
  press Play and run it from the Isaac Sim Script Editor to publish depth / point cloud /
  camera info / IMU.
