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

The installer finds Isaac Sim and **registers the extension to auto-load on every launch** by:
1. linking/copying it into Isaac Sim's `extsUser/` folder (already on the extension search path), and
2. adding `econ.itof.menu` to the Full app's `.kit` `[dependencies]` — exactly how the built-in
   vendors (Intel/Stereolabs) load.

> Why `.kit` and not the persistent config? Editing Isaac Sim 5.1's `user.config.json`
> (ext folders / enabled flags) is silently reset on the next launch (IsaacSim issues
> #376 / #377). `.kit` files are read fresh from disk each launch and never rewritten, so this
> sticks. A `start-isaacsim-econ.sh` / `.bat` launcher is also written as a belt-and-suspenders
> fallback (it passes `--ext-folder … --enable`).

### Use it
1. **If Isaac Sim is open, fully close it.** Then launch Isaac Sim **normally** (App Selector or
   your usual command) — no special launcher needed; the camera is now built in.
2. **Create → Sensors → Camera and Depth Sensors → e-con → DepthVista Helix iToF (USB)** or **(GMSL)**.
3. (Optional) start ROS 2 streaming: open the Script Editor and run `ros2/isaac_usd_ros_itof.py`
   — it auto-discovers the camera you added and publishes depth / points / camera_info / IMU.

### Uninstall
```bash
python3 scripts/patch_kit.py "<isaac>/apps" econ.itof.menu --uninstall   # restores .kit from .bak
rm "<isaac>/extsUser/econ.itof.menu"
```

### Notes
- Re-run `build.sh` / `build.bat` after **reinstalling or updating Isaac Sim** (the `.kit` edit
  lives inside the install).
- If Isaac Sim isn't auto-detected: `ISAACSIM_PATH=/path/to/isaacsim ./build.sh`.
