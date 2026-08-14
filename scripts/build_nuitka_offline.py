#!/usr/bin/env python3
"""
ChromaBeam Offline Nuitka Dual Build Script (Linux & Windows)
Produces both:
1. --standalone (Folder distribution for instant startup)
2. --onefile (Single portable standalone binary)
Zero internet / Zero bandwidth required — uses pre-installed packages in Henny's central venv.
"""

import os
import sys
import subprocess
import shutil

VENV_PYTHON = "/home/henry/Documents/Projects/Python/venv/bin/python"
PROJECT_DIR = "/home/henry/Documents/Projects/Python/QR ChromaBeam"
DIST_DIR = os.path.join(PROJECT_DIR, "dist")

def main():
    if not os.path.exists(VENV_PYTHON):
        print(f"❌ Error: Central venv python not found at {VENV_PYTHON}")
        sys.exit(1)

    os.chdir(PROJECT_DIR)
    os.makedirs(DIST_DIR, exist_ok=True)

    print("=" * 60)
    print("🚀 ChromaBeam Offline Nuitka Dual Packaging Engine")
    print(f"📁 Project: {PROJECT_DIR}")
    print(f"📦 Output:  {DIST_DIR}")
    print("=" * 60)

    # 1. Standalone Build (Folder Distribution - Fast Startup)
    print("\n[1/2] 🔨 Compiling Nuitka Standalone Bundle (Fast Startup)...")
    cmd_standalone = [
        VENV_PYTHON, "-m", "nuitka",
        "--standalone",
        "--enable-plugin=pyqt6",
        "--include-package=core",
        "--include-package=desktop_receiver",
        "--include-package=desktop_sender",
        "--include-data-dir=assets=assets",
        "--include-data-file=chromabeam_offline.html=chromabeam_offline.html",
        "--linux-icon=assets/icon.png",
        f"--output-dir={DIST_DIR}/standalone",
        "--assume-yes-for-downloads",
        "desktop_app.py"
    ]
    print(f"Command: {' '.join(cmd_standalone)}")
    ret1 = subprocess.run(cmd_standalone)
    if ret1.returncode != 0:
        print(f"❌ Standalone build failed with code {ret1.returncode}")
    else:
        print("✅ Standalone build finished successfully!")

    # 2. Onefile Build (Single Portable Executable)
    print("\n[2/2] 🔨 Compiling Nuitka Onefile Binary (Single Portable Executable)...")
    cmd_onefile = [
        VENV_PYTHON, "-m", "nuitka",
        "--onefile",
        "--enable-plugin=pyqt6",
        "--include-package=core",
        "--include-package=desktop_receiver",
        "--include-package=desktop_sender",
        "--include-data-dir=assets=assets",
        "--include-data-file=chromabeam_offline.html=chromabeam_offline.html",
        "--linux-icon=assets/icon.png",
        f"--output-dir={DIST_DIR}/onefile",
        "--output-filename=ChromaBeam",
        "--assume-yes-for-downloads",
        "desktop_app.py"
    ]
    print(f"Command: {' '.join(cmd_onefile)}")
    ret2 = subprocess.run(cmd_onefile)
    if ret2.returncode != 0:
        print(f"❌ Onefile build failed with code {ret2.returncode}")
    else:
        print("✅ Onefile build finished successfully!")

    print("\n" + "=" * 60)
    print("🎉 Offline Builds Complete!")
    print(f"📦 Standalone App: {DIST_DIR}/standalone/desktop_app.dist/")
    print(f"📦 Onefile Binary: {DIST_DIR}/onefile/ChromaBeam")
    print("=" * 60)

if __name__ == '__main__':
    main()
