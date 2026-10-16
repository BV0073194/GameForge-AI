"""Conservative, project-scoped WSL artifact cleanup.

Never runs distro-wide prune commands, never removes build outputs or toolchains,
and refuses to follow symlinks or clean an unmarked Linux worktree.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import PurePosixPath
from typing import Any

# This code executes *inside* the selected WSL distro using python3 -c.
# The root must be an explicitly configured GameForge-owned directory.
WSL_CLEANUP_SCRIPT = r'''
import json, os, pathlib, shutil, sys, time
root = pathlib.Path(sys.argv[1])
age = int(sys.argv[2])
report = {"deleted_files": 0, "deleted_dirs": 0, "reclaimed_bytes": 0, "skipped": [], "errors": []}
def output():
    print(json.dumps(report, sort_keys=True))
if not root.is_absolute() or ".." in root.parts or root.is_symlink() or not root.is_dir():
    report["errors"].append("Unsafe or missing WSL project root"); output(); sys.exit(2)
root = root.resolve()
if str(root) in ("/", "/home", "/tmp", "/var", "/mnt", "/usr", "/opt"):
    report["errors"].append("Refusing broad WSL root"); output(); sys.exit(2)
marker = root / ".gameforge"
if not marker.is_dir() or marker.is_symlink():
    report["skipped"].append("No GameForge-owned .gameforge directory in WSL root"); output(); sys.exit(0)
# Only disposable GameForge-private directories, not project sources, dependencies,
# ROMs, release assets, general Linux caches, or compiler/build output.
allowed = [marker / "tmp", marker / "temp", marker / "cache", marker / "scratch"]
cutoff = time.time() - age
for directory in allowed:
    if directory.is_symlink() or not directory.is_dir():
        continue
    for base, dirs, files in os.walk(directory, topdown=False, followlinks=False):
        for name in files:
            path = pathlib.Path(base) / name
            try:
                if path.is_symlink() or not path.is_file() or path.stat().st_mtime >= cutoff:
                    continue
                size = path.stat().st_size
                path.unlink()
                report["deleted_files"] += 1
                report["reclaimed_bytes"] += size
            except OSError as exc:
                report["errors"].append(str(exc)[:180])
        for name in dirs:
            path = pathlib.Path(base) / name
            try:
                if path.is_symlink():
                    continue
                path.rmdir()  # only empty directories
                report["deleted_dirs"] += 1
            except OSError:
                pass
output()
'''


def cleanup_wsl_project(
    *,
    root: str,
    distro: str = "",
    min_age_hours: int = 48,
    timeout_sec: int = 25,
) -> dict[str, Any]:
    """Prune old GameForge-owned temp files in a single WSL project.

    Never invokes a shell. Invalid roots/distro names are rejected before WSL.
    """
    report: dict[str, Any] = {
        "enabled": True, "root": root, "distro": distro,
        "deleted_files": 0, "deleted_dirs": 0, "reclaimed_bytes": 0,
        "skipped": [], "errors": [],
    }
    if os.name != "nt":
        report["skipped"].append("WSL cleanup only runs from Windows")
        return report
    if not isinstance(root, str) or not root.startswith("/") or "\x00" in root:
        report["errors"].append("WSL project root must be an absolute Linux path")
        return report
    if ".." in PurePosixPath(root).parts or root in ("/", "/home", "/mnt", "/tmp", "/var", "/opt", "/usr"):
        report["errors"].append("WSL root is too broad or contains traversal")
        return report
    if distro and not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", distro):
        report["errors"].append("Invalid WSL distribution")
        return report
    command = ["wsl.exe"]
    if distro:
        command.extend(["--distribution", distro])
    command.extend(["--exec", "python3", "-c", WSL_CLEANUP_SCRIPT, root, str(max(24, int(min_age_hours)) * 3600)])
    try:
        proc = subprocess.run(
            command, capture_output=True, text=True, errors="replace",
            timeout=max(5, min(int(timeout_sec), 60)), check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode:
            report["errors"].append(f"WSL cleanup exited {proc.returncode}: {proc.stderr[-400:]}")
        if proc.stdout.strip():
            data = json.loads(proc.stdout.strip().splitlines()[-1])
            if isinstance(data, dict):
                for key in ("deleted_files", "deleted_dirs", "reclaimed_bytes", "skipped", "errors"):
                    if key in data:
                        report[key] = data[key] if key not in ("skipped", "errors") else report[key] + data[key]
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError) as exc:
        report["errors"].append(str(exc)[:500])
    return report
