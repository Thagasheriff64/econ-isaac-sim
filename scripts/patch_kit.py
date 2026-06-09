#!/usr/bin/env python3
"""Add (or remove) the e-con extension as a dependency of Isaac Sim's Full .kit apps.

Isaac Sim 5.1's persistent user config silently drops ext folders / enabled flags
(IsaacSim issues #376/#377), so we register the extension the config-bug-proof way:
as a `[dependencies]` entry in the app `.kit` files, which Isaac reads fresh from disk
on every launch and never rewrites — exactly how the built-in vendors load.

Usage:
    patch_kit.py <isaac_apps_dir> <ext_name> [--uninstall]

Idempotent. A one-time `<kit>.bak` is written before the first edit so --uninstall
(or manual restore) is clean.
"""
import glob
import os
import sys


def kit_files(appdir: str) -> list:
    return sorted(glob.glob(os.path.join(appdir, "isaacsim.exp.full*.kit")))


def install(appdir: str, ext: str) -> int:
    kits = kit_files(appdir)
    if not kits:
        print(f"[WARN] no isaacsim.exp.full*.kit found in {appdir}")
        return 1
    for kit in kits:
        s = open(kit).read()
        if ext in s:
            print(f"[INFO] already enabled in {os.path.basename(kit)}")
            continue
        if not os.path.exists(kit + ".bak"):
            open(kit + ".bak", "w").write(s)
        out, done = [], False
        for line in s.splitlines(keepends=True):
            out.append(line)
            if not done and line.strip() == "[dependencies]":
                out.append(f'"{ext}" = {{}}  # e-con DepthVista Helix iToF camera menu\n')
                done = True
        if done:
            open(kit, "w").write("".join(out))
            print(f"[INFO] enabled in {os.path.basename(kit)} (autoload on every launch)")
        else:
            print(f"[WARN] no [dependencies] section in {os.path.basename(kit)} — skipped")
    return 0


def uninstall(appdir: str, ext: str) -> int:
    for kit in kit_files(appdir):
        if os.path.exists(kit + ".bak"):
            open(kit, "w").write(open(kit + ".bak").read())
            os.remove(kit + ".bak")
            print(f"[INFO] restored {os.path.basename(kit)} from backup")
        else:
            # No backup (e.g. line added by hand) — strip the dependency line directly.
            lines = [ln for ln in open(kit).read().splitlines(keepends=True)
                     if not (ext in ln and ln.strip().startswith(f'"{ext}"'))]
            open(kit, "w").write("".join(lines))
            print(f"[INFO] removed {ext} from {os.path.basename(kit)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    appdir, ext = os.path.expanduser(sys.argv[1]), sys.argv[2]
    sys.exit(uninstall(appdir, ext) if "--uninstall" in sys.argv[3:] else install(appdir, ext))
