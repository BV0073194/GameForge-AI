# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import json
import os
import subprocess
from pathlib import Path

datas = [("web", "web")]
build_info_path = Path("build_info.json")
if not build_info_path.exists():
    branch = ""
    commit = ""
    try:
        branch = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, timeout=5).stdout.strip()
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        pass
    channel = "main" if branch == "main" else ("experimental" if branch.startswith("experimental/") else (branch or "unknown"))
    build_info_path.write_text(json.dumps({"channel": channel, "ref": branch, "commit": commit}, indent=2), encoding="utf-8")
if build_info_path.exists():
    datas.append(("build_info.json", "."))
binaries = []
hiddenimports = []

for pkg in ["cv2", "mss", "psutil", "numpy", "pynput"]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

if os.name == "nt":
    try:
        d, b, h = collect_all("pygetwindow")
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ["gameforge_desktop.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GameForgeAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
