# econ-isaac-sim

Distribute the **e-con DepthVista Helix iToF** cameras for **NVIDIA Isaac Sim** the same way
Stereolabs ships ZED: clone this repo, run the install script, and the camera appears under
**Create → Sensors → Camera and Depth Sensors → e-con**.

Unlike ZED there is **nothing to compile** — the integration is a pure-Python extension, so the
install script only clones and registers it.

## Repository layout

```
econ-isaac-sim/
├── build.sh / build.bat          # installer (Linux / Windows)
├── exts/
│   └── econ.itof.menu/           # the Isaac Sim extension (adds the Create-menu entries)
│       ├── config/extension.toml
│       ├── econ/itof/menu/…      # extension.py — builds the menu, references the USDs
│       └── assets/               # the camera USDs the menu drops into the stage
│           ├── DEPTH_VISTA_HELIX_USB.usd
│           └── DEPTH_VISTA_HELIX_GMSL.usd
└── ros2/
    └── isaac_usd_ros_itof.py     # ROS 2 depth/points/IMU streaming driver (run in Script Editor)
```

---

## Part A — Put it on GitHub (do this once, on your machine)

You have the USDs and ROS 2 code locally but no repo yet. From the `econ-isaac-sim/` folder:

```bash
cd econ-isaac-sim

# (optional) add the rest of your ROS 2 package next to the driver:
#   cp -r /path/to/your_ros2_pkg ros2/

git init
git add .
git commit -m "e-con DepthVista Helix iToF — Isaac Sim integration"

# create an empty repo on github.com first (e.g. econ-systems/econ-isaac-sim), then:
git branch -M main
git remote add origin https://github.com/Thagasheriff64/econ-isaac-sim.git
git push -u origin main
```

> The USDs are ~2 MB each (fine for plain git). If you later add much larger binaries, consider
> [Git LFS](https://git-lfs.com): `git lfs track "*.usd"`.

The clone URL is already baked into **`build.sh`** / **`build.bat`** (`REPO_URL=…
Thagasheriff64/econ-isaac-sim.git`), so end users don't pass anything. If you move/rename the
repo, update that line in both files and push again.

---

## Part B — Install on another PC (the end user)

Requirements on the target PC: **git** and **Isaac Sim 5.1** installed.

### Linux
```bash
git clone https://github.com/Thagasheriff64/econ-isaac-sim.git
cd econ-isaac-sim
./build.sh
# if Isaac Sim isn't auto-found:  ISAACSIM_PATH=/path/to/isaacsim ./build.sh
```

### Windows
```bat
git clone https://github.com/Thagasheriff64/econ-isaac-sim.git
cd econ-isaac-sim
build.bat
:: if Isaac Sim isn't auto-found:  set ISAACSIM_PATH=C:\path\to\isaacsim  &  build.bat
```

The installer clones/verifies the extension, finds Isaac Sim, and writes a launcher
**`start-isaacsim-econ.sh`** / **`start-isaacsim-econ.bat`** next to the repo.

> Why a launcher? Editing Isaac Sim 5.1's persistent extension config is unreliable (it can be
> silently reset; see IsaacSim issues #376 / #377). The launcher passes
> `--ext-folder … --enable econ.itof.menu` so the camera loads reliably every time. The
> installer also *attempts* the persistent-config write as a bonus (non-fatal if it doesn't
> stick).

### Use it
1. Launch Isaac Sim via the generated **`start-isaacsim-econ`** script.
2. **Create → Sensors → Camera and Depth Sensors → e-con → DepthVista Helix iToF (USB)** or **(GMSL)**.
3. (Optional) start ROS 2 streaming: open the Script Editor and run `ros2/isaac_usd_ros_itof.py`
   — it auto-discovers the camera you added and publishes depth / points / camera_info / IMU.

### Manual fallback (if Isaac Sim isn't auto-detected)
Window → Extensions → (gear) add `<repo>/exts` to the search paths → enable **econ.itof.menu**
in the Third-Party tab.
