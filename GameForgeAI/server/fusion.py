from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _steam_roots() -> list[Path]:
    candidates: list[Path] = []
    if os.name == "nt":
        for env in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
            base = os.environ.get(env)
            if base:
                candidates.append(Path(base) / "Steam")
    else:
        candidates += [
            Path.home() / ".steam" / "steam",
            Path.home() / ".local" / "share" / "Steam",
        ]
    out: list[Path] = []
    seen: set[str] = set()
    for root in candidates:
        key = str(root).lower() if os.name == "nt" else str(root)
        if root.exists() and key not in seen:
            seen.add(key)
            out.append(root)
    return out


def _parse_steam_libraries(text: str) -> list[Path]:
    out: list[Path] = []
    for match in re.finditer(r'"path"\s*"([^"]+)"', text, re.I):
        raw = match.group(1).replace("\\\\", "\\")
        path = Path(raw)
        if path not in out:
            out.append(path)
    return out


def detect_installed_games() -> dict[str, Any]:
    games: list[dict[str, Any]] = []
    libraries: list[Path] = []
    for root in _steam_roots():
        if root not in libraries:
            libraries.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            try:
                for lib in _parse_steam_libraries(vdf.read_text(encoding="utf-8", errors="replace")):
                    if lib not in libraries:
                        libraries.append(lib)
            except Exception:
                pass

    for library in libraries:
        apps = library / "steamapps"
        if not apps.exists():
            continue
        for manifest in apps.glob("appmanifest_*.acf"):
            try:
                text = manifest.read_text(encoding="utf-8", errors="replace")
                def field(name: str) -> str:
                    m = re.search(rf'"{re.escape(name)}"\s*"([^"]*)"', text, re.I)
                    return m.group(1) if m else ""
                appid, name, installdir = field("appid"), field("name"), field("installdir")
                if not appid or not name or not installdir:
                    continue
                install = apps / "common" / installdir
                games.append({
                    "store": "steam",
                    "id": appid,
                    "name": name,
                    "version": field("buildid"),
                    "install_dir": str(install),
                    "exists": install.exists(),
                })
            except Exception:
                continue

    if os.name == "nt":
        programdata = os.environ.get("PROGRAMDATA")
        if programdata:
            manifest_dir = Path(programdata) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
            if manifest_dir.exists():
                for item in manifest_dir.glob("*.item"):
                    data = _read_json(item, {})
                    if not isinstance(data, dict):
                        continue
                    install = Path(str(data.get("InstallLocation", "") or ""))
                    name = str(data.get("DisplayName") or data.get("AppName") or "")
                    if not name or not str(install):
                        continue
                    games.append({
                        "store": "epic",
                        "id": str(data.get("CatalogItemId") or data.get("AppName") or ""),
                        "name": name,
                        "version": str(data.get("AppVersionString") or ""),
                        "install_dir": str(install),
                        "exists": install.exists(),
                    })

    games.sort(key=lambda x: (str(x.get("name", "")).lower(), str(x.get("store", ""))))
    return {"scanned_at": _now_iso(), "count": len(games), "games": games}


def _safe_project_source(project_root: Path, rel: str) -> Path:
    rel = str(rel or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in Path(rel).parts:
        raise ValueError("Invalid project-relative source path")
    source = (project_root / rel).resolve()
    if project_root.resolve() not in source.parents and source != project_root.resolve():
        raise ValueError("Source path escapes project")
    return source


def _safe_target(target_root: Path, rel: str) -> Path:
    rel = str(rel or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in Path(rel).parts:
        raise ValueError("Invalid target-relative path")
    target = (target_root / rel).resolve()
    if target_root.resolve() not in target.parents:
        raise ValueError("Target path escapes target root")
    return target


def _expand_mapping(project_root: Path, target_root: Path, mapping: dict[str, Any]) -> list[tuple[Path, Path, str]]:
    src_rel = str(mapping.get("source", "") or "")
    dst_rel = str(mapping.get("target", "") or "")
    src = _safe_project_source(project_root, src_rel)
    if not src.exists():
        raise FileNotFoundError(f"Fusion source does not exist: {src_rel}")
    pairs: list[tuple[Path, Path, str]] = []
    if src.is_file():
        dst = _safe_target(target_root, dst_rel or src.name)
        pairs.append((src, dst, src_rel))
        return pairs
    base_target = _safe_target(target_root, dst_rel or src.name)
    for file in src.rglob("*"):
        if file.is_file():
            rel_inside = file.relative_to(src)
            pairs.append((file, (base_target / rel_inside).resolve(), f"{src_rel}/{rel_inside}".replace("\\", "/")))
    return pairs


def deploy_reversible(project_root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    fusion = cfg.get("fusion", {}) if isinstance(cfg.get("fusion"), dict) else {}
    deployment = fusion.get("deployment", {}) if isinstance(fusion.get("deployment"), dict) else {}
    target_raw = str(deployment.get("target_root", "") or "").strip()
    mappings = deployment.get("mappings", [])
    if not target_raw:
        return {"ok": False, "error": "Fusion deployment target_root is not configured."}
    if not isinstance(mappings, list) or not mappings:
        return {"ok": False, "error": "Fusion deployment has no file mappings."}

    target_root = Path(target_raw).expanduser().resolve()
    if not target_root.exists():
        return {"ok": False, "error": f"Target root does not exist: {target_root}"}

    receipt_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    backup_root = project_root / ".gameforge" / "fusion_backups" / receipt_id
    entries: list[dict[str, Any]] = []
    try:
        pairs: list[tuple[Path, Path, str]] = []
        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue
            pairs.extend(_expand_mapping(project_root, target_root, mapping))
        if not pairs:
            return {"ok": False, "error": "Fusion deployment mappings resolved to no files."}

        for idx, (src, dst, src_rel) in enumerate(pairs):
            if target_root not in dst.parents:
                raise ValueError(f"Deployment target escaped root: {dst}")
            existed = dst.exists()
            backup_rel = f"{idx:06d}-{dst.name}"
            backup = backup_root / backup_rel
            previous_sha = ""
            if existed:
                if not dst.is_file():
                    raise ValueError(f"Refusing to overwrite non-file target: {dst}")
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, backup)
                previous_sha = _sha256(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            deployed_sha = _sha256(dst)
            entries.append({
                "source": src_rel,
                "target": str(dst),
                "target_relative": str(dst.relative_to(target_root)).replace("\\", "/"),
                "existed_before": existed,
                "previous_sha256": previous_sha,
                "deployed_sha256": deployed_sha,
                "backup": str(backup.relative_to(project_root)).replace("\\", "/") if existed else "",
            })

        receipt = {
            "format": "GameForgeAI.FusionDeployment",
            "version": 1,
            "id": receipt_id,
            "created_at": _now_iso(),
            "project_root": str(project_root),
            "target_root": str(target_root),
            "entries": entries,
            "restored": False,
        }
        receipt_path = backup_root / "receipt.json"
        _write_json(receipt_path, receipt)
        _write_json(project_root / ".gameforge" / "fusion_last_deployment.json", receipt)
        return {"ok": True, "receipt": receipt, "receipt_path": str(receipt_path)}
    except Exception as exc:
        # Roll back anything already written in this deployment attempt.
        for entry in reversed(entries):
            try:
                dst = Path(entry["target"])
                if entry["existed_before"]:
                    backup = project_root / entry["backup"]
                    if backup.exists():
                        shutil.copy2(backup, dst)
                elif dst.exists():
                    dst.unlink()
            except Exception:
                pass
        return {"ok": False, "error": str(exc), "rolled_back_partial_deploy": True}


def restore_deployment(project_root: Path, *, force: bool = False) -> dict[str, Any]:
    receipt = _read_json(project_root / ".gameforge" / "fusion_last_deployment.json", {})
    if not isinstance(receipt, dict) or not receipt.get("entries"):
        return {"ok": False, "error": "No reversible Fusion deployment receipt exists."}
    if receipt.get("restored"):
        return {"ok": True, "already_restored": True, "receipt": receipt}

    conflicts: list[str] = []
    for entry in receipt["entries"]:
        dst = Path(entry["target"])
        if dst.exists() and dst.is_file():
            current = _sha256(dst)
            if current != entry.get("deployed_sha256") and not force:
                conflicts.append(str(dst))
    if conflicts:
        return {
            "ok": False,
            "conflict": True,
            "error": "Target files changed after Fusion deployment. Refusing to overwrite them without force.",
            "files": conflicts,
        }

    restored = 0
    for entry in reversed(receipt["entries"]):
        dst = Path(entry["target"])
        if entry.get("existed_before"):
            backup = project_root / str(entry.get("backup", ""))
            if not backup.exists():
                return {"ok": False, "error": f"Required backup is missing: {backup}"}
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, dst)
        elif dst.exists() and dst.is_file():
            dst.unlink()
        restored += 1

    receipt["restored"] = True
    receipt["restored_at"] = _now_iso()
    receipt_path = project_root / ".gameforge" / "fusion_backups" / str(receipt["id"]) / "receipt.json"
    _write_json(receipt_path, receipt)
    _write_json(project_root / ".gameforge" / "fusion_last_deployment.json", receipt)
    return {"ok": True, "restored_files": restored, "receipt": receipt}


def record_run_report(project_root: Path, report: dict[str, Any]) -> dict[str, Any]:
    data = _read_json(project_root / ".gameforge" / "fusion_run_reports.json", {}) or {}
    reports = data.get("reports") if isinstance(data, dict) else None
    if not isinstance(reports, list):
        reports = []
    row = {
        "id": f"run-{int(time.time() * 1000)}",
        "created_at": _now_iso(),
        **report,
    }
    reports.append(row)
    data = {"updated_at": _now_iso(), "reports": reports[-200:]}
    _write_json(project_root / ".gameforge" / "fusion_run_reports.json", data)
    return row


def run_reports(project_root: Path) -> dict[str, Any]:
    data = _read_json(project_root / ".gameforge" / "fusion_run_reports.json", {}) or {}
    reports = data.get("reports", []) if isinstance(data, dict) else []
    return {"count": len(reports), "reports": reports[-50:]}


def create_creator_bundle(project_root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Create an authorized source/release handoff without copying external game installs."""
    fusion = cfg.get("fusion", {}) if isinstance(cfg.get("fusion"), dict) else {}
    release = fusion.get("release", {}) if isinstance(fusion.get("release"), dict) else {}
    roots = release.get("roots") or ["workspace/release"]
    if not isinstance(roots, list):
        roots = ["workspace/release"]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = project_root / ".gameforge" / "fusion_exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"creator-bundle-{stamp}.zip"
    included: list[str] = []
    fixed_files = ["AGENTS.md", "goal.md", "gameforge.json", ".gameforge/acceptance.json"]

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, strict_timestamps=False) as zf:
        for rel in fixed_files:
            file = project_root / rel
            if file.is_file():
                zf.write(file, rel)
                included.append(rel)
        for rel_root in roots:
            try:
                root = _safe_project_source(project_root, str(rel_root))
            except Exception:
                continue
            if not root.exists():
                continue
            if root.is_file():
                arc = str(root.relative_to(project_root)).replace("\\", "/")
                zf.write(root, arc)
                included.append(arc)
            else:
                for file in root.rglob("*"):
                    if file.is_file():
                        arc = str(file.relative_to(project_root)).replace("\\", "/")
                        zf.write(file, arc)
                        included.append(arc)

        handoff = {
            "format": "GameForgeAI.CreatorHandoff",
            "version": 1,
            "created_at": _now_iso(),
            "project": {"id": cfg.get("id"), "name": cfg.get("name"), "goal": cfg.get("goal")},
            "quality": {
                "acceptance": _read_json(project_root / ".gameforge" / "acceptance.json", {}),
                "last_evidence": _read_json(project_root / ".gameforge" / "last_evidence.json", {}),
            },
            "included_files": included,
            "external_game_files_included": False,
            "melty_note": "Connect this project only through Melty's official creator/coding-agent tools. GameForge does not use undocumented Melty APIs.",
        }
        zf.writestr("GAMEFORGE_CREATOR_HANDOFF.json", json.dumps(handoff, indent=2, ensure_ascii=False))

    with zipfile.ZipFile(out, "r") as zf:
        bad = zf.testzip()
        if bad:
            out.unlink(missing_ok=True)
            return {"ok": False, "error": f"Creator bundle failed ZIP verification at {bad}"}
    return {"ok": True, "path": str(out), "files": len(included), "sha256": _sha256(out)}
