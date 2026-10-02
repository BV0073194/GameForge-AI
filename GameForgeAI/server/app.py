from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import platform
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
import atexit
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

def _resource_root() -> Path:
    # PyInstaller one-file/one-dir extracts bundled resources to sys._MEIPASS.
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return Path(__file__).resolve().parents[1]


def _user_data_root() -> Path:
    override = os.environ.get("GAMEFORGE_USER_DATA")
    if override:
        return Path(override).expanduser().resolve()
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "GameForgeAI"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "GameForgeAI"
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "gameforgeai"


RESOURCE_ROOT = _resource_root()
USER_DATA = _user_data_root()
WEB = RESOURCE_ROOT / "web"
PROJECTS = USER_DATA / "projects"
GLOBAL_UPLOAD = USER_DATA / "UPLOAD"
GLOBAL_LOGS = USER_DATA / "logs"
AUTH_TRACE = GLOBAL_LOGS / "codex-auth-live.jsonl"
AUTH_TRACE_LOCK = threading.Lock()
REGISTRY_FILE = USER_DATA / "project_registry.json"
RUNTIME = USER_DATA / "runtime"
CODEX_RUNTIME = RUNTIME / "codex"
RUNTIME_STATE = {"codex_installing": False, "codex_install_error": "", "codex_install_message": "", "session_login": False, "codex_login_in_progress": False, "codex_login_message": "", "codex_login_process": None}

EXPERIMENT_FORMAT = "GameForgeAI.Experiment"
EXPERIMENT_FORMAT_VERSION = 1
EXPERIMENT_BRANCH = "experimental/fast-iteration-pipeline"

for p in (USER_DATA, PROJECTS, GLOBAL_UPLOAD, GLOBAL_LOGS, RUNTIME, CODEX_RUNTIME):
    p.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


_AUTH_SECRET_RE = re.compile(r'(?i)(bearer\\s+)[^\\s,"]+|(sk-[A-Za-z0-9_-]{8,})|("(?:access_token|refresh_token|id_token|api_key|cookie|authorization)"\\s*:\\s*")[^"]+(")')

def _auth_redact(value: Any) -> Any:
    """Recursively redact auth material before it can touch the live trace."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if re.search(r"(?i)(token|secret|password|cookie|authorization|api.?key)", str(k)):
                # Presence-only diagnostic fields deliberately contain only
                # SET/unset. Preserve those labels; redact every other value.
                out[k] = v if v in ("SET", "unset") else ("<REDACTED:PRESENT>" if v else "<EMPTY>")
            else:
                out[k] = _auth_redact(v)
        return out
    if isinstance(value, list):
        return [_auth_redact(v) for v in value]
    if isinstance(value, str):
        return _AUTH_SECRET_RE.sub(lambda m: (m.group(1) or "") + "<REDACTED>" + (m.group(4) or ""), value)
    return value

def auth_trace(event: str, **fields: Any) -> None:
    """Append a secret-safe, line-buffered event for live Codex auth debugging."""
    try:
        AUTH_TRACE.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": now_iso(), "event": event, "pid": os.getpid(), "thread": threading.current_thread().name, **fields}
        line = json.dumps(_auth_redact(record), ensure_ascii=False, default=str)
        with AUTH_TRACE_LOCK:
            with AUTH_TRACE.open("a", encoding="utf-8", buffering=1) as fp:
                fp.write(line + "\\n")
                fp.flush()
        print("[AUTH-TRACE] " + line, flush=True)
    except Exception:
        pass

def _auth_store_snapshot() -> dict[str, Any]:
    home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    auth = home / "auth.json"
    snap: dict[str, Any] = {"codex_home": str(home), "auth_path": str(auth), "auth_exists": auth.exists()}
    if auth.exists():
        try:
            st = auth.stat()
            snap.update({"auth_size": st.st_size, "auth_mtime_ns": st.st_mtime_ns})
            data = json.loads(auth.read_text(encoding="utf-8", errors="replace"))
            snap["auth_top_level_keys"] = sorted(data.keys()) if isinstance(data, dict) else [type(data).__name__]
        except Exception as exc:
            snap["auth_metadata_error"] = repr(exc)
    return snap

def _auth_env_snapshot(env: dict[str, str] | None = None) -> dict[str, Any]:
    env = env or os.environ
    names = ("CODEX_HOME","OPENAI_BASE_URL","OPENAI_API_BASE","OPENAI_API_KEY","CODEX_API_KEY","CODEX_ACCESS_TOKEN","HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","NO_PROXY")
    return {name: ("SET" if env.get(name) else "unset") for name in names}

def _watch_auth_store(stop: threading.Event) -> None:
    previous = None
    while not stop.wait(0.25):
        current = _auth_store_snapshot()
        signature = (current.get("auth_exists"), current.get("auth_size"), current.get("auth_mtime_ns"))
        if signature != previous:
            auth_trace("credential_store_changed", **current)
            previous = signature


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return (value or "game-project")[:64]


def safe_child(root: Path, rel: str) -> Path:
    root = root.resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path escapes project root")
    return target


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def runtime_build_info() -> dict[str, Any]:
    """Describe the source/release channel so experimental promotion can be gated safely."""
    info = read_json(RESOURCE_ROOT / "build_info.json", {}) or {}
    if not isinstance(info, dict):
        info = {}
    branch = str(os.environ.get("GAMEFORGE_BUILD_REF") or info.get("ref") or "").strip()
    channel = str(os.environ.get("GAMEFORGE_BUILD_CHANNEL") or info.get("channel") or "").strip()
    commit = str(info.get("commit") or "").strip()

    # Source checkouts can determine their branch directly. Frozen builds use the
    # build_info.json stamped by CI and bundled by PyInstaller.
    if not branch and not getattr(sys, "frozen", False) and command_exists("git"):
        for candidate in (RESOURCE_ROOT, RESOURCE_ROOT.parent):
            try:
                proc = subprocess.run(
                    ["git", "-C", str(candidate), "branch", "--show-current"],
                    capture_output=True, text=True, timeout=4,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    branch = proc.stdout.strip()
                    break
            except Exception:
                pass

    if not channel:
        if branch == "main":
            channel = "main"
        elif branch.startswith("experimental/"):
            channel = "experimental"
        else:
            channel = branch or "unknown"
    return {
        "channel": channel,
        "ref": branch or info.get("ref") or "",
        "commit": commit,
        "experimental_branch": EXPERIMENT_BRANCH,
    }


def load_project_registry() -> dict[str, str]:
    data = read_json(REGISTRY_FILE, {})
    return data if isinstance(data, dict) else {}


def save_project_registry(registry: dict[str, str]) -> None:
    write_json(REGISTRY_FILE, registry)


def register_project_root(root: Path, project_id: str | None = None) -> str:
    root = root.expanduser().resolve()
    cfg = read_json(root / "gameforge.json", {})
    pid = slugify(project_id or cfg.get("id") or root.name)
    if not (root / "gameforge.json").exists():
        raise FileNotFoundError(f"No gameforge.json in project root: {root}")
    registry = load_project_registry()
    registry[pid] = str(root)
    save_project_registry(registry)
    return pid


def project_manifest(project_root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://gameforgeai.local/schema/gfai-project-v1.json",
        "format": "GameForgeAI.Project",
        "format_version": 1,
        "project_id": cfg["id"],
        "name": cfg.get("name", cfg["id"]),
        "root": ".",
        "config": "gameforge.json",
        "goal": "goal.md",
        "uploads": "UPLOAD",
        "project_index": ".gameforge/project_index.json",
        "created_at": cfg.get("created_at", now_iso()),
    }


def write_gfai_manifest(project_root: Path, cfg: dict[str, Any]) -> Path:
    filename = f"{slugify(cfg.get('name') or cfg['id'])}.gfai"
    path = project_root / filename
    write_json(path, project_manifest(project_root, cfg))
    return path


def scan_project_tree(project_root: Path, max_files: int = 100000) -> dict[str, Any]:
    ignored_dirs = {".git", ".venv", "node_modules", "__pycache__", ".gameforge/cache"}
    items: list[dict[str, Any]] = []
    truncated = False
    for base, dirs, files in os.walk(project_root):
        b = Path(base)
        rel_base = b.relative_to(project_root)
        dirs[:] = [d for d in dirs if d not in ignored_dirs]
        for name in files:
            f = b / name
            try:
                rel = str(f.relative_to(project_root)).replace("\\", "/")
                st = f.stat()
                items.append({
                    "path": rel,
                    "bytes": st.st_size,
                    "extension": f.suffix.lower(),
                    "mtime": int(st.st_mtime),
                })
            except Exception:
                continue
            if len(items) >= max_files:
                truncated = True
                break
        if truncated:
            break
    report = {
        "indexed_at": now_iso(),
        "root": str(project_root),
        "file_count": len(items),
        "truncated": truncated,
        "items": items,
    }
    write_json(project_root / ".gameforge" / "project_index.json", report)
    return report


def open_gfai_file(path: str | Path) -> tuple[str, Path, dict[str, Any]]:
    manifest_path = Path(path).expanduser().resolve()
    if manifest_path.suffix.lower() != ".gfai":
        raise ValueError("Project entry point must end in .gfai")
    manifest = read_json(manifest_path, None)
    if not isinstance(manifest, dict) or manifest.get("format") != "GameForgeAI.Project":
        raise ValueError("Invalid or unsupported .gfai project file")
    if int(manifest.get("format_version", 0)) != 1:
        raise ValueError("Unsupported .gfai format version")
    root_value = str(manifest.get("root", "."))
    project_root = (manifest_path.parent / root_value).resolve()
    repair_project_layout(project_root)
    cfg_path = project_root / str(manifest.get("config", "gameforge.json"))
    cfg = read_json(cfg_path, {})
    if not cfg:
        raise FileNotFoundError(f"Project config not found: {cfg_path}")
    pid = register_project_root(project_root, manifest.get("project_id") or cfg.get("id"))
    scan_project_tree(project_root)
    return pid, project_root, cfg


def tail_text(path: Path, max_bytes: int = 40000) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            n = f.tell()
            f.seek(max(0, n - max_bytes))
            return f.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def refresh_windows_environment() -> dict[str, Any]:
    """Refresh this process from canonical Windows Machine + User environment.

    Long-running Explorer/terminal processes can hand GameForge a stale PATH after
    installers update the registry. Read the current values directly without
    mutating the user's configuration.
    """
    if os.name != "nt":
        return {"refreshed": False, "reason": "not-windows"}
    try:
        import winreg
        def reg_value(root, key_path: str, name: str) -> str:
            try:
                with winreg.OpenKey(root, key_path) as key:
                    value, _ = winreg.QueryValueEx(key, name)
                    return os.path.expandvars(str(value))
            except OSError:
                return ""
        machine = reg_value(winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment", "Path")
        user = reg_value(winreg.HKEY_CURRENT_USER, r"Environment", "Path")
        entries, seen = [], set()
        for raw in (machine, user):
            for item in raw.split(";"):
                # A single unmatched quote anywhere in PATH can make cmd.exe fail
                # to execute programs that 'where' can still locate. Sanitize each
                # registry entry independently for GameForge's process only.
                item = os.path.expandvars(item.strip().replace('"', "").strip())
                key = item.rstrip("\\/").lower()
                if item and key not in seen:
                    seen.add(key)
                    entries.append(item)

        # Known Windows tool locations are process-local fallbacks only. Never
        # rewrite the user's Machine/User PATH from GameForge.
        fallbacks = [
            Path(os.environ.get("ProgramFiles", r"C:\\Program Files")) / "nodejs",
            Path(os.environ.get("ProgramFiles", r"C:\\Program Files")) / "Git" / "cmd",
            Path(os.environ.get("ProgramFiles", r"C:\\Program Files")) / "CMake" / "bin",
            Path(os.environ.get("APPDATA", "")) / "npm",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "OpenAI" / "Codex" / "bin",
        ]
        prepend = []
        for p in fallbacks:
            if p and p.exists():
                key = str(p).rstrip("\\/").lower()
                if key not in seen:
                    seen.add(key)
                    prepend.append(str(p))
        entries = prepend + entries

        if entries:
            os.environ["PATH"] = os.pathsep.join(entries)

        # Report actual executable health, not merely whether a PATH entry exists.
        health = {}
        for command in ("node", "git", "python", "py", "cmake"):
            resolved = shutil.which(command)
            health[command] = resolved or ""
        return {"refreshed": True, "path_entries": len(entries), "commands": health}
    except Exception as exc:
        return {"refreshed": False, "error": str(exc)}


def _codex_candidates() -> list[Path]:
    exe = "codex.exe" if os.name == "nt" else "codex"
    candidates = [
        CODEX_RUNTIME / exe,
        Path.home() / ".codex" / "bin" / exe,
        Path.home() / ".local" / "bin" / exe,
    ]
    if os.name == "nt":
        candidates += [
            # Official OpenAI standalone installer visible launcher.
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "OpenAI" / "Codex" / "bin" / exe,
            # Current managed standalone payload.
            Path.home() / ".codex" / "packages" / "standalone" / "current" / "bin" / exe,
            # Legacy npm shim is last-resort only and requires Node.
            Path(os.environ.get("APPDATA", "")) / "npm" / "codex.cmd",
        ]
    return [p for p in candidates if p.exists()]


def resolve_command(name: str) -> str | None:
    if os.name == "nt":
        refresh_windows_environment()
    # Prefer GameForge/native Codex over npm shims. A codex.cmd can exist on
    # Windows while its Node runtime is missing, which otherwise looks installed
    # until every agent iteration fails with '"node" is not recognized'.
    if name == "codex":
        candidates = _codex_candidates()
        native = [p for p in candidates if p.suffix.lower() not in {".cmd", ".bat"}]
        if native:
            return str(native[0])
        resolved = shutil.which(name)
        if resolved and Path(resolved).suffix.lower() not in {".cmd", ".bat"}:
            return resolved
        # A Node-backed shim is usable only when Node itself is present.
        shim = resolved or (str(candidates[0]) if candidates else None)
        if shim and Path(shim).suffix.lower() in {".cmd", ".bat"} and shutil.which("node"):
            return shim
        return None
    return shutil.which(name)


def command_exists(name: str) -> bool:
    return resolve_command(name) is not None


def install_codex(force: bool = False) -> dict[str, Any]:
    if command_exists("codex") and not force:
        return {"ok": True, "already_installed": True, "path": resolve_command("codex")}
    if RUNTIME_STATE["codex_installing"]:
        return {"ok": False, "installing": True}
    RUNTIME_STATE["codex_installing"] = True
    RUNTIME_STATE["codex_install_error"] = ""
    RUNTIME_STATE["codex_install_message"] = "Installing official Codex CLI..."
    try:
        system = platform.system()
        if system == "Windows":
            ps = shutil.which("powershell") or shutil.which("pwsh")
            if not ps:
                raise RuntimeError("PowerShell is required to install Codex on Windows")
            cmd = [ps, "-NoProfile", "-ExecutionPolicy", "ByPass", "-Command", "irm https://github.com/openai/codex/releases/latest/download/install.ps1 | iex"]
        elif system in {"Linux", "Darwin"}:
            shell = shutil.which("sh") or "/bin/sh"
            if not shutil.which("curl"):
                raise RuntimeError("curl is required for the official Codex installer")
            cmd = [shell, "-c", "curl -fsSL https://github.com/openai/codex/releases/latest/download/install.sh | sh"]
        else:
            raise RuntimeError(f"Automatic Codex install is not supported on {system}")
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=900)
        if proc.returncode != 0:
            raise RuntimeError(((proc.stdout or "") + "\n" + (proc.stderr or ""))[-4000:])
        bin_dir = str(Path.home() / ".codex" / "bin")
        if bin_dir not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        resolved = resolve_command("codex")
        if not resolved:
            raise RuntimeError("Codex installer completed, but GameForge could not locate the executable")
        RUNTIME_STATE["codex_install_message"] = "Codex installed"
        return {"ok": True, "path": resolved}
    except Exception as exc:
        RUNTIME_STATE["codex_install_error"] = str(exc)
        RUNTIME_STATE["codex_install_message"] = "Codex installation failed: " + str(exc)
        return {"ok": False, "error": str(exc)}
    finally:
        RUNTIME_STATE["codex_installing"] = False


def ensure_codex_async(force: bool = False) -> None:
    if (command_exists("codex") and not force) or RUNTIME_STATE["codex_installing"]:
        return
    threading.Thread(target=install_codex, args=(force,), daemon=True, name="codex-installer").start()


def codex_auth_status() -> dict[str, Any]:
    if not command_exists("codex"):
        return {"authenticated": False, "available": False, "message": "Codex is not installed"}
    try:
        proc = run_codex(["login", "status"], timeout=15)
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return {"available": True, "authenticated": proc.returncode == 0, "message": output[-2000:] or ("Authenticated" if proc.returncode == 0 else "Sign in required")}
    except Exception as exc:
        return {"available": True, "authenticated": False, "message": str(exc)}


def _watch_codex_login(proc: subprocess.Popen, save_login: bool, store_stop: threading.Event) -> None:
    try:
        auth_trace("oauth_process_waiting", child_pid=proc.pid, save_login=save_login)
        code = proc.wait()
        auth_trace("oauth_process_exited", child_pid=proc.pid, exit_code=code, **_auth_store_snapshot())
        status = codex_auth_status()
        auth_trace("post_oauth_login_status", status=status, **_auth_store_snapshot())
        # Doctor is diagnostic-only and its output is redacted before logging.
        try:
            doctor = run_codex(["doctor", "--json"], timeout=30)
            auth_trace("post_oauth_doctor", exit_code=doctor.returncode,
                       output=((doctor.stdout or "") + "\\n" + (doctor.stderr or ""))[-12000:])
        except Exception as exc:
            auth_trace("post_oauth_doctor_error", error=repr(exc))
        if status.get("authenticated"):
            RUNTIME_STATE["codex_login_message"] = "Authenticated"
            RUNTIME_STATE["session_login"] = False
        else:
            RUNTIME_STATE["codex_login_message"] = status.get("message") or f"Sign-in exited with code {code}"
    except Exception as exc:
        auth_trace("oauth_watcher_exception", error=repr(exc))
        RUNTIME_STATE["codex_login_message"] = str(exc)
    finally:
        store_stop.set()
        RUNTIME_STATE["codex_login_in_progress"] = False
        RUNTIME_STATE["codex_login_process"] = None
        auth_trace("oauth_watch_finished", **_auth_store_snapshot())

def start_codex_login(save_login: bool = True) -> dict[str, Any]:
    if RUNTIME_STATE.get("codex_login_in_progress"):
        return {"ok": True, "in_progress": True, "message": "ChatGPT sign-in is already in progress."}
    status = codex_auth_status()
    if status.get("authenticated"):
        return {"ok": True, "authenticated": True, "message": "Already authenticated"}
    if not command_exists("codex"):
        result = install_codex()
        if not result.get("ok"): return result
    try:
        command, use_shell = _command_invocation("codex", ["login", "-c", 'cli_auth_credentials_store="file"'])
        env = _codex_process_env()
        auth_trace("oauth_start_requested", save_login=save_login, requested_credentials_store="file", codex=resolve_command("codex"),
                   command=command, use_shell=use_shell, cwd=str(USER_DATA),
                   env=_auth_env_snapshot(env), config=_codex_config_diagnostics(), **_auth_store_snapshot())
        store_stop = threading.Event()
        threading.Thread(target=_watch_auth_store, args=(store_stop,), daemon=True, name="codex-auth-store-watch").start()
        # Keep stdout/stderr attached so Codex's local-login-server and browser
        # messages remain visible live in the GameForge console.
        proc = subprocess.Popen(command, shell=use_shell, cwd=str(USER_DATA), env=env)
        auth_trace("oauth_process_started", child_pid=proc.pid)
        RUNTIME_STATE["codex_login_process"] = proc
        RUNTIME_STATE["codex_login_in_progress"] = True
        RUNTIME_STATE["codex_login_message"] = "Complete the official ChatGPT sign-in in your browser."
        threading.Thread(target=_watch_codex_login, args=(proc, save_login, store_stop), daemon=True, name="codex-login-watch").start()
        return {"ok": True, "started": True, "save_login": save_login, "trace_path": str(AUTH_TRACE), "message": RUNTIME_STATE["codex_login_message"]}
    except Exception as exc:
        RUNTIME_STATE["codex_login_in_progress"] = False
        RUNTIME_STATE["codex_login_message"] = str(exc)
        return {"ok": False, "error": str(exc)}


def codex_auth_preflight(cwd: Path | None = None) -> dict[str, Any]:
    """Verify that Codex can make an authenticated inference, not just read local login state."""
    status = codex_auth_status()
    if not status.get("authenticated"):
        return {"ok": False, "kind": "not_logged_in", "message": status.get("message") or "Sign in to Codex"}
    try:
        proc = run_codex(
            ["exec", "--json", "--skip-git-repo-check", "--sandbox", "read-only", "-"],
            cwd=cwd or USER_DATA,
            input_text="Reply with exactly: GAMEFORGE_AUTH_OK",
            timeout=60,
        )
        combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        lower = combined.lower()
        if proc.returncode == 0:
            return {"ok": True, "kind": "ready", "message": "Codex authenticated and ready"}
        if "401 unauthorized" in lower or "missing bearer or basic authentication" in lower:
            diag = _codex_config_diagnostics()
            if "api.openai.com/v1/responses" in lower and (diag.get("provider_override") or diag.get("base_url_override")):
                return {"ok": False, "kind": "provider_mismatch", "message": "ChatGPT sign-in succeeded, but Codex is being routed to api.openai.com by a Codex provider/base-URL override. Remove the custom provider/openai_base_url override from the reported Codex config, then Resume.", "diagnostics": diag}
            return {"ok": False, "kind": "transport_401", "message": "ChatGPT sign-in succeeded, but the installed Codex runtime sent the inference request without usable authentication (401). Project state is preserved; GameForge will not consume an agent iteration.", "diagnostics": diag}
        return {"ok": False, "kind": "exec_failed", "message": combined[-2000:] or f"Codex preflight exited with {proc.returncode}"}
    except Exception as exc:
        return {"ok": False, "kind": "preflight_error", "message": str(exc)}


def codex_logout() -> dict[str, Any]:
    if not command_exists("codex"):
        return {"ok": True, "message": "Codex is not installed"}
    try:
        proc = run_codex(["logout"], timeout=30)
        RUNTIME_STATE["session_login"] = False
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return {"ok": proc.returncode == 0, "message": output[-2000:]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _logout_session_auth() -> None:
    """Do not mutate the user's global Codex credential store on GameForge exit.

    Explicit Sign out remains available through /api/codex/logout. Historically
    this function called codex logout for a session-only GameForge login, which
    deleted ~/.codex/auth.json and made a successful OAuth flow appear broken.
    """
    return


atexit.register(_logout_session_auth)


def _command_invocation(name: str, args: list[str]) -> tuple[str | list[str], bool]:
    """Return a subprocess-compatible invocation for native commands and Windows npm shims.

    npm global executables on Windows are commonly exposed as .cmd/.bat shims.
    CreateProcess cannot reliably execute those the same way it executes an .exe,
    so route only those shim types through the Windows command processor.
    """
    resolved = resolve_command(name)
    if not resolved:
        raise FileNotFoundError(f"{name} was not found on PATH")

    suffix = Path(resolved).suffix.lower()
    if os.name == "nt" and suffix in {".cmd", ".bat"}:
        # The argument list here is composed by GameForge from trusted constants,
        # while large/user project prompts are sent on stdin instead of the shell
        # command line. This also avoids cmd.exe's much smaller command-length limit.
        command = subprocess.list2cmdline([resolved, *args])
        return command, True

    return [resolved, *args], False


def _gameforge_process_env() -> dict[str, str]:
    """Return a stable child-process environment for local/WSL build tooling.

    When Windows-hosted projects are built through WSL, uv's cache commonly
    lives on the Linux filesystem while the project/venv is under /mnt/c or
    /mnt/d. Hardlinks cannot cross those filesystems, so uv repeatedly warns
    before falling back to copies. Copy mode is the intended safe behavior for
    that layout; export it into WSL as well as native child processes.
    """
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    if os.name == "nt":
        env.setdefault("UV_LINK_MODE", "copy")
        env.setdefault("DEBIAN_FRONTEND", "noninteractive")
        entries = [x for x in env.get("WSLENV", "").split(":") if x]
        for name in ("UV_LINK_MODE", "DEBIAN_FRONTEND", "GIT_TERMINAL_PROMPT"):
            if not any(x.split("/", 1)[0] == name for x in entries):
                entries.append(name + "/u")
        env["WSLENV"] = ":".join(entries)
    return env


def _codex_process_env() -> dict[str, str]:
    """Give Codex a clean provider-routing environment while preserving credentials.

    ChatGPT OAuth must be allowed to select Codex's ChatGPT backend. A stale
    OPENAI_BASE_URL or provider override can incorrectly route the OAuth session
    to api.openai.com/v1/responses, where ChatGPT OAuth is not the API-key auth
    expected by that route. Keep supported credential variables intact.
    """
    env = _gameforge_process_env()
    for name in ("OPENAI_BASE_URL", "OPENAI_API_BASE"):
        env.pop(name, None)
    return env


def _codex_config_diagnostics() -> dict[str, Any]:
    """Report provider-routing overrides without reading or returning secrets."""
    home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    config = home / "config.toml"
    result: dict[str, Any] = {
        "config_path": str(config),
        "config_exists": config.exists(),
        "provider_override": False,
        "base_url_override": False,
    }
    try:
        if config.exists():
            text = config.read_text(encoding="utf-8", errors="replace")
            result["provider_override"] = bool(re.search(r"(?m)^\\s*model_provider\\s*=", text))
            result["base_url_override"] = bool(re.search(r"(?m)^\\s*(?:openai_base_url|base_url)\\s*=.*api\\.openai\\.com", text, re.I))
    except Exception as exc:
        result["error"] = str(exc)
    return result


def run_codex(
    args: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    timeout: int = 3600,
) -> subprocess.CompletedProcess[str]:
    command, use_shell = _command_invocation("codex", args)
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        shell=use_shell,
        input=input_text,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        env=_codex_process_env(),
    )


def _terminate_process_tree(proc: subprocess.Popen | None, *, grace_sec: float = 1.5) -> None:
    """Stop a subprocess and its descendants, escalating quickly if needed."""
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
                proc.wait(timeout=grace_sec)
                return
            except Exception:
                pass
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True, text=True, timeout=8,
                )
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=grace_sec)
                return
            except Exception:
                pass
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    finally:
        try:
            proc.wait(timeout=3)
        except Exception:
            pass


def _bind_active_process(state: AgentState | None, proc: subprocess.Popen | None, kind: str) -> None:
    if state is None:
        return
    state.active_process = proc
    state.active_process_kind = kind if proc is not None else ""
    state.active_process_started_at = now_iso() if proc is not None else None


def stop_agent_now(state: AgentState) -> None:
    """Request stop immediately; kill an active child tree without blocking the UI request."""
    state.stop_event.set()
    state.pause_event.clear()
    state.status = "stopping"
    state.message = "Stopping active AI/build/test process…"
    set_agent_activity(state, "Stopping", state.message, "stop")
    proc = state.active_process
    if proc is not None and proc.poll() is None:
        threading.Thread(
            target=_terminate_process_tree,
            args=(proc,),
            kwargs={"grace_sec": 1.0},
            daemon=True,
            name=f"agent-stop-{state.project_id}",
        ).start()


def run_shell(command: str, cwd: Path, timeout: int = 1800, log_path: Path | None = None, activity_state: AgentState | None = None) -> dict[str, Any]:
    if not command.strip():
        return {"configured": False, "ok": True, "exit_code": None, "output": ""}
    started = time.time()
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    proc: subprocess.Popen | None = None
    try:
        kwargs: dict[str, Any] = {
            "cwd": str(cwd),
            "shell": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "errors": "replace",
            "env": _gameforge_process_env(),
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(command, **kwargs)
        _bind_active_process(activity_state, proc, "project-command")

        def read_pipe(pipe, target: list[str]) -> None:
            if pipe is None:
                return
            for line in pipe:
                target.append(line)
                if len(target) > 5000:
                    del target[:1000]

        out_thread = threading.Thread(target=read_pipe, args=(proc.stdout, stdout_lines), daemon=True)
        err_thread = threading.Thread(target=read_pipe, args=(proc.stderr, stderr_lines), daemon=True)
        out_thread.start(); err_thread.start()

        cancelled = False
        timed_out = False
        while proc.poll() is None:
            if activity_state is not None:
                if activity_state.stop_event.is_set():
                    cancelled = True
                    _terminate_process_tree(proc, grace_sec=1.0)
                    break
                set_agent_activity(
                    activity_state,
                    activity_state.current_task or "Running project tooling",
                    activity_state.current_detail or command,
                    "heartbeat",
                    history=False,
                )
            if time.time() - started >= timeout:
                timed_out = True
                _terminate_process_tree(proc, grace_sec=1.0)
                break
            time.sleep(0.2)

        try:
            proc.wait(timeout=3)
        except Exception:
            _terminate_process_tree(proc, grace_sec=0.5)
        out_thread.join(timeout=2); err_thread.join(timeout=2)

        # stop_agent_now() terminates the child tree from a separate thread so the
        # UI remains responsive. On fast exits (notably Windows CTRL_BREAK_EVENT,
        # which commonly returns 0xC000013A / 3221225786) the process can disappear
        # before this polling loop gets another chance to set cancelled=True.
        # The stop_event is therefore the authoritative cancellation signal.
        if activity_state is not None and activity_state.stop_event.is_set() and not timed_out:
            cancelled = True

        output = "".join(stdout_lines) + ("\n" if stdout_lines and stderr_lines else "") + "".join(stderr_lines)
        if cancelled:
            result = {
                "configured": True, "ok": False, "cancelled": True,
                "exit_code": proc.returncode, "duration_sec": round(time.time() - started, 2),
                "output": ("STOPPED BY USER\n" + output)[-80000:],
            }
        elif timed_out:
            result = {
                "configured": True, "ok": False, "timed_out": True,
                "exit_code": proc.returncode, "duration_sec": round(time.time() - started, 2),
                "output": (f"TIMEOUT after {timeout}s\n" + output)[-80000:],
            }
        else:
            result = {
                "configured": True,
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "duration_sec": round(time.time() - started, 2),
                "output": output[-80000:],
            }
    except Exception as exc:
        result = {"configured": True, "ok": False, "exit_code": None, "output": repr(exc)}
    finally:
        if activity_state is not None and activity_state.active_process is proc:
            _bind_active_process(activity_state, None, "")
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(result["output"], encoding="utf-8", errors="replace")
    return result


def repair_project_layout(p: Path) -> None:
    for rel in ("logs", "research", "workspace", "captures", ".gameforge", "UPLOAD"):
        (p / rel).mkdir(parents=True, exist_ok=True)


def project_path(project_id: str) -> Path:
    pid = slugify(project_id)
    registry = load_project_registry()
    if pid in registry:
        p = Path(registry[pid]).expanduser().resolve()
        if p.exists():
            repair_project_layout(p)
            return p
    p = safe_child(PROJECTS, pid)
    if p.exists():
        repair_project_layout(p)
    return p


def project_config(project_id: str) -> dict[str, Any]:
    p = project_path(project_id)
    cfg = read_json(p / "gameforge.json", {})
    if not cfg:
        raise FileNotFoundError(project_id)
    return cfg


DEFAULT_ITERATION_PIPELINE = {
    "enabled": True,
    "quality_mode": "strict-original",
    "strict_original_quality": True,
    "compact_context": True,
    "targeted_tests_during_ai_turn": True,
    "targeted_tests_are_diagnostic_only": True,
    "gameforge_full_verification_after_turn": True,
    "full_configured_build_required": True,
    "full_configured_test_required": True,
    "allow_savestate_for_trusted_evidence": False,
    "allow_direct_warp_for_trusted_evidence": False,
    "allow_fast_forward_for_trusted_evidence": False,
    "batch_related_feedback": True,
}


def iteration_pipeline_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return the production fast-iteration policy, preserving strict original-quality gates."""
    settings = dict(DEFAULT_ITERATION_PIPELINE)
    configured = cfg.get("iteration_pipeline")
    # Compatibility with project copies created while this pipeline was experimental.
    if not isinstance(configured, dict):
        configured = cfg.get("experimental_pipeline")
    if isinstance(configured, dict):
        settings.update(configured)
    return settings


def _experiment_meta_path(p: Path) -> Path:
    return p / ".gameforge" / "experiment.json"


def _experiment_link_path(p: Path) -> Path:
    return p / ".gameforge" / "experimental_link.json"


def _tree_size_bytes(root: Path) -> int:
    total = 0
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in files:
            f = Path(base) / name
            try:
                if not f.is_symlink():
                    total += f.stat().st_size
            except OSError:
                pass
    return total


def _copy_project_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        raise FileExistsError(str(dst))
    shutil.copytree(src, dst, symlinks=True, ignore_dangling_symlinks=True)


def _snapshot_ready(project_id: str) -> tuple[bool, str]:
    state = AGENTS.get(project_id)
    if state and state.thread and state.thread.is_alive() and state.status not in {
        "paused", "blocked", "complete", "user-complete", "stopped", "error"
    }:
        return False, "Pause the autonomous developer between iterations before creating or promoting an experimental snapshot."
    cv = CVS.get(project_id)
    if cv and cv.thread and cv.thread.is_alive():
        cv.stop_event.set()
        cv.thread.join(timeout=3)
    proc = managed_process_public(project_id)
    if proc.get("running"):
        stopped = stop_managed_process(project_id)
        if not stopped.get("ok"):
            return False, "Could not stop the managed game/process safely before snapshotting."
    return True, ""


def experiment_status(p: Path) -> dict[str, Any]:
    build = runtime_build_info()
    override = os.environ.get("GAMEFORGE_ALLOW_EXPERIMENT_PROMOTION") == "1"
    promotion_allowed = build.get("channel") == "main" or override
    meta = read_json(_experiment_meta_path(p), {}) or {}
    link = read_json(_experiment_link_path(p), {}) or {}
    if isinstance(meta, dict) and meta.get("format") == EXPERIMENT_FORMAT:
        source = Path(str(meta.get("source_project_path", ""))).expanduser()
        return {
            "role": "experimental",
            "active": True,
            "state": meta.get("state", "active"),
            "source_project_id": meta.get("source_project_id", ""),
            "source_project_path": str(source),
            "initial_backup_path": meta.get("initial_backup_path", ""),
            "created_at": meta.get("created_at", ""),
            "promotion_allowed": promotion_allowed,
            "promotion_gate": "main",
            "build": build,
        }
    if isinstance(link, dict) and link.get("format") == EXPERIMENT_FORMAT:
        experimental = Path(str(link.get("experimental_project_path", ""))).expanduser()
        return {
            "role": "original",
            "active": experimental.exists(),
            "experimental_project_id": link.get("experimental_project_id", ""),
            "experimental_project_path": str(experimental),
            "initial_backup_path": link.get("initial_backup_path", ""),
            "created_at": link.get("created_at", ""),
            "promotion_allowed": False,
            "promotion_gate": "main",
            "build": build,
        }
    return {
        "role": "original",
        "active": False,
        "promotion_allowed": False,
        "promotion_gate": "main",
        "build": build,
    }


def create_experimental_copy(project_id: str) -> dict[str, Any]:
    p = project_path(project_id).resolve()
    cfg = project_config(project_id)
    status = experiment_status(p)
    if status.get("role") == "experimental":
        return {"ok": False, "status": 409, "error": "This project is already the experimental copy."}
    if status.get("active"):
        return {
            "ok": True,
            "existing": True,
            "experimental_project_id": status.get("experimental_project_id"),
            "experimental_project_path": status.get("experimental_project_path"),
            "initial_backup_path": status.get("initial_backup_path"),
        }

    ready, reason = _snapshot_ready(project_id)
    if not ready:
        return {"ok": False, "status": 409, "error": reason}

    source_id = slugify(cfg.get("id") or project_id)
    exp_id = slugify(f"{source_id}-experimental")
    exp_root = p.parent / f"{p.name}-experimental"
    if exp_root.exists():
        return {"ok": False, "status": 409, "error": f"Experimental folder already exists: {exp_root}"}

    size = _tree_size_bytes(p)
    free = shutil.disk_usage(p.parent).free
    required = max(size * 2 + 512 * 1024 * 1024, 1024 * 1024 * 1024)
    if free < required:
        return {
            "ok": False,
            "status": 507,
            "error": f"Not enough free disk space for a full backup plus experimental copy. Need about {required // (1024**2)} MiB free.",
        }

    git_checkpoint(p, "GameForge pre-experimental-copy checkpoint")
    token = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = p.parent / f"{p.name}.gameforge-backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / f"pre-experimental-{token}"

    try:
        _copy_project_tree(p, backup)
        _copy_project_tree(p, exp_root)
    except Exception as exc:
        if exp_root.exists():
            shutil.rmtree(exp_root, ignore_errors=True)
        return {
            "ok": False,
            "status": 500,
            "error": f"Snapshot copy failed. The original project was not modified. {exc}",
            "backup_path": str(backup) if backup.exists() else "",
        }

    exp_cfg = read_json(exp_root / "gameforge.json", {}) or {}
    original_name = str(cfg.get("name") or p.name)
    exp_cfg["id"] = exp_id
    exp_cfg["name"] = f"{original_name} [Experimental]"
    exp_cfg["experimental"] = {
        "enabled": True,
        "branch": EXPERIMENT_BRANCH,
        "source_project_id": source_id,
        "source_project_path": str(p),
    }
    exp_cfg["experimental_pipeline"] = {
        "enabled": True,
        "quality_mode": "strict-original",
        "strict_original_quality": True,
        "compact_context": True,
        "targeted_tests_during_ai_turn": True,
        "targeted_tests_are_diagnostic_only": True,
        "gameforge_full_verification_after_turn": True,
        "full_configured_build_required": True,
        "full_configured_test_required": True,
        "allow_savestate_for_trusted_evidence": False,
        "allow_direct_warp_for_trusted_evidence": False,
        "allow_fast_forward_for_trusted_evidence": False,
        "batch_related_feedback": True,
    }
    write_json(exp_root / "gameforge.json", exp_cfg)
    for manifest in exp_root.glob("*.gfai"):
        try:
            manifest.unlink()
        except OSError:
            pass
    write_gfai_manifest(exp_root, exp_cfg)

    meta = {
        "format": EXPERIMENT_FORMAT,
        "format_version": EXPERIMENT_FORMAT_VERSION,
        "state": "active",
        "branch": EXPERIMENT_BRANCH,
        "created_at": now_iso(),
        "source_project_id": source_id,
        "source_project_name": original_name,
        "source_project_path": str(p),
        "experimental_project_id": exp_id,
        "experimental_project_path": str(exp_root),
        "initial_backup_path": str(backup),
        "created_by_build": runtime_build_info(),
        "promotion_requires_channel": "main",
    }
    write_json(_experiment_meta_path(exp_root), meta)
    write_json(_experiment_link_path(p), meta)
    register_project_root(exp_root, exp_id)
    scan_project_tree(exp_root)
    return {
        "ok": True,
        "experimental_project_id": exp_id,
        "experimental_project_path": str(exp_root),
        "initial_backup_path": str(backup),
        "size_bytes": size,
    }


def promote_experimental_copy(project_id: str, confirmed: bool) -> dict[str, Any]:
    exp_root = project_path(project_id).resolve()
    meta = read_json(_experiment_meta_path(exp_root), {}) or {}
    if not isinstance(meta, dict) or meta.get("format") != EXPERIMENT_FORMAT:
        return {"ok": False, "status": 409, "error": "This project is not an experimental copy."}
    if not confirmed:
        return {"ok": False, "status": 400, "error": "Promotion requires explicit user confirmation."}

    build = runtime_build_info()
    if build.get("channel") != "main" and os.environ.get("GAMEFORGE_ALLOW_EXPERIMENT_PROMOTION") != "1":
        return {
            "ok": False,
            "status": 403,
            "error": "Promotion is locked until the experimental GameForge branch is merged and you run a main-channel build.",
        }

    source_id = slugify(str(meta.get("source_project_id") or ""))
    source_root = Path(str(meta.get("source_project_path") or "")).expanduser().resolve()
    if not source_id or not source_root.exists() or not (source_root / "gameforge.json").exists():
        return {"ok": False, "status": 409, "error": "The original project folder could not be found."}

    for pid in (project_id, source_id):
        ready, reason = _snapshot_ready(pid)
        if not ready:
            return {"ok": False, "status": 409, "error": reason}

    git_checkpoint(exp_root, "GameForge pre-promotion experimental checkpoint")
    git_checkpoint(source_root, "GameForge pre-promotion original checkpoint")

    size = _tree_size_bytes(exp_root) + _tree_size_bytes(source_root)
    free = shutil.disk_usage(source_root.parent).free
    required = size + 512 * 1024 * 1024
    if free < required:
        return {"ok": False, "status": 507, "error": "Not enough free disk space to create the mandatory pre-promotion backup and staging copy."}

    token = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = source_root.parent / f"{source_root.name}.gameforge-backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / f"pre-promotion-{token}"
    staging = source_root.parent / f".{source_root.name}.promotion-staging-{token}"
    displaced = source_root.parent / f".{source_root.name}.promotion-old-{token}"

    try:
        _copy_project_tree(source_root, backup)
        _copy_project_tree(exp_root, staging)

        promoted_cfg = read_json(staging / "gameforge.json", {}) or {}
        promoted_cfg["id"] = source_id
        promoted_cfg["name"] = str(meta.get("source_project_name") or promoted_cfg.get("name") or source_root.name).replace(" [Experimental]", "")
        promoted_cfg.pop("experimental", None)
        write_json(staging / "gameforge.json", promoted_cfg)
        for manifest in staging.glob("*.gfai"):
            try:
                manifest.unlink()
            except OSError:
                pass
        write_gfai_manifest(staging, promoted_cfg)
        for marker in (_experiment_meta_path(staging), _experiment_link_path(staging)):
            try:
                marker.unlink()
            except OSError:
                pass
        write_json(staging / ".gameforge" / "promotion_receipt.json", {
            "promoted_at": now_iso(),
            "from_experimental_project": str(exp_root),
            "from_branch": EXPERIMENT_BRANCH,
            "pre_promotion_backup": str(backup),
            "accepted_by_user": True,
            "build": build,
        })

        source_root.rename(displaced)
        try:
            staging.rename(source_root)
        except Exception:
            displaced.rename(source_root)
            raise
        shutil.rmtree(displaced, ignore_errors=True)
    except Exception as exc:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        return {
            "ok": False,
            "status": 500,
            "error": f"Promotion failed and the original project was preserved/restored where possible: {exc}",
            "backup_path": str(backup) if backup.exists() else "",
        }

    registry = load_project_registry()
    registry[source_id] = str(source_root)
    registry.pop(slugify(project_id), None)
    save_project_registry(registry)

    meta["state"] = "promoted"
    meta["promoted_at"] = now_iso()
    meta["pre_promotion_backup_path"] = str(backup)
    meta["promoted_build"] = build
    write_json(_experiment_meta_path(exp_root), meta)
    scan_project_tree(source_root)
    return {
        "ok": True,
        "original_project_id": source_id,
        "original_project_path": str(source_root),
        "pre_promotion_backup_path": str(backup),
        "experimental_project_path": str(exp_root),
    }


def create_project(name: str, goal: str, research_mode: str = "deep") -> dict[str, Any]:
    pid_base = slugify(name)
    pid = pid_base
    i = 2
    while (PROJECTS / pid).exists():
        pid = f"{pid_base}-{i}"
        i += 1
    p = PROJECTS / pid
    for rel in [
        "UPLOAD/MODELS", "UPLOAD/TEXTURES", "UPLOAD/ANIMATIONS", "UPLOAD/AUDIO", "UPLOAD/UI",
        "UPLOAD/REFERENCE", "UPLOAD/MODS", "UPLOAD/SOURCE", "UPLOAD/REPOS", "UPLOAD/TOOLS",
        "UPLOAD/DOCS", "UPLOAD/ROMS_LOCAL", "workspace", "research", "logs", "captures", ".gameforge"
    ]:
        (p / rel).mkdir(parents=True, exist_ok=True)

    cfg = {
        "id": pid,
        "name": name.strip() or pid,
        "created_at": now_iso(),
        "goal": goal.strip(),
        "research_mode": research_mode if research_mode in {"off", "normal", "deep", "exhaustive"} else "deep",
        "internet_research": True,
        "commands": {"build": "", "test": "", "launch": ""},
        "command_timeout_sec": 1800,
        "iteration_pipeline": dict(DEFAULT_ITERATION_PIPELINE),
        "agent": {
            "permission_mode": "full-auto",
            "max_iterations": 0,
            "cooldown_sec": 3,
            "max_auto_recovery_attempts": 8,
        },
        "visual": {
            "monitor": 1,
            "interval_sec": 1.0,
            "freeze_seconds": 8,
            "black_mean_threshold": 8.0,
            "region": None,
            "window_title": "",
        },
        "log_globs": ["logs/**/*", "*.log", "**/*.log"],
    }
    write_json(p / "gameforge.json", cfg)
    (p / "goal.md").write_text(f"# User Goal\n\n{goal.strip()}\n", encoding="utf-8")
    acceptance = {
        "project_complete": False,
        "updated_at": now_iso(),
        "criteria": [
            {"id": "playable", "description": "A playable build matching the user's goal exists", "status": "pending", "evidence": ""},
            {"id": "regression", "description": "Previously working required gameplay still passes regression checks", "status": "pending", "evidence": ""},
            {"id": "packaged", "description": "A reproducible playable build/package is produced", "status": "pending", "evidence": ""},
        ],
    }
    write_json(p / ".gameforge/acceptance.json", acceptance)
    save_user_review(p, {"user_done": False, "satisfaction": None, "feedback": []})
    (p / "AGENTS.md").write_text(UNIVERSAL_AGENTS.format(goal=goal.strip(), research=cfg["research_mode"]), encoding="utf-8")
    (p / "UPLOAD/README.txt").write_text(UPLOAD_README, encoding="utf-8")
    if command_exists("git"):
        subprocess.run(["git", "init"], cwd=p, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=p, capture_output=True)
        subprocess.run(["git", "commit", "-m", "GameForge AI project bootstrap"], cwd=p, capture_output=True)
    register_project_root(p, pid)
    write_gfai_manifest(p, cfg)
    scan_project_tree(p)
    return cfg


UNIVERSAL_AGENTS = r'''# GameForge AI — Persistent Game Development Contract

## User goal
{goal}

## Scope
This project is ONLY for playable video-game content: game creation, editing, modding,
mission/level work, ROM/decomp workflows, total conversions, game-mechanic fusion,
asset adaptation, debugging, playtesting, performance work, and packaging.

## Non-negotiable development standard
- Preserve the user's original intent across iterations.
- Research before guessing. Research mode: {research}.
- When internet research tools are available, use public/authorized sources broadly:
  official docs, open-source repos, archived developer material, interviews, dev logs,
  issue trackers, technical papers, modding research, public reverse engineering, and
  verified game concepts. Track useful sources in research/SOURCES.md and distinguish
  confirmed facts from reported concepts, rumors, and project-original ideas.
- Inspect UPLOAD/ at the start of each iteration. User-supplied assets may be converted,
  optimized, restyled, retopologized, resized, re-rigged, or otherwise adapted to fit
  the target game's art style and technical constraints, but never silently replace
  provenance or licensing metadata.
- Never fabricate engine APIs, build success, test success, or runtime behavior.
- Work in small reversible milestones. Keep Git clean enough to recover.
- Use build output, runtime logs, crash data, screenshots/video, OpenCV reports,
  performance telemetry, and repeatable input/play tests whenever available.
- A compile is NOT completion. A feature is known-good only after relevant runtime and
  regression evidence supports it.
- If a change breaks a previously required working behavior, repair it or roll it back.
- Keep iterating toward a full playable result until explicit acceptance criteria pass,
  the user stops the run, usage is unavailable, or a genuine technical blocker is proven.
- Record blockers honestly rather than claiming completion.

## Completion contract
Maintain `.gameforge/acceptance.json`. Set project_complete=true only when the explicit
criteria are satisfied by concrete evidence. Evidence should point to test output, logs,
visual reports/captures, reproducible steps, or release artifacts. Do not mark criteria
pass merely because you believe the code should work.

## Distribution hygiene
Do not package stolen/private source, pirated commercial game images, credentials, or
unauthorized proprietary assets. Prefer patches, original assets/code, or workflows that
require the user to provide their own legally obtained base game/ROM where applicable.
'''

UPLOAD_README = '''GAMEFORGE AI UPLOAD INTAKE\n\nDrop authorized project materials into the matching folder.\nOriginal uploads are treated as inputs and should not be destructively modified.\n\nMODELS, TEXTURES, ANIMATIONS, AUDIO, UI: project assets\nREFERENCE: screenshots/video/concept references\nMODS: existing mods\nSOURCE: source/decomp/codebases\nREPOS: cloned/downloaded public repositories\nTOOLS: authorized helper tools\nDOCS: manuals/specifications/research\nROMS_LOCAL: legally obtained personal ROMs for local build/test workflows; do not redistribute\n'''


@dataclass
class AgentState:
    project_id: str
    status: str = "idle"
    iteration: int = 0
    message: str = ""
    started_at: str | None = None
    last_update: str | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    pause_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    input_request: dict[str, Any] | None = None
    current_task: str = "Idle"
    current_detail: str = ""
    task_started_at: str | None = None
    last_activity_at: str | None = None
    activity_history: list[dict[str, Any]] = field(default_factory=list)
    active_process: subprocess.Popen | None = field(default=None, repr=False)
    active_process_kind: str = ""
    active_process_started_at: str | None = None


@dataclass
class CVState:
    project_id: str
    status: str = "idle"
    message: str = ""
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


AGENTS: dict[str, AgentState] = {}
CVS: dict[str, CVState] = {}
STATE_LOCK = threading.Lock()
MANAGED_PROCESSES: dict[str, subprocess.Popen] = {}
MANAGED_PROCESS_META: dict[str, dict[str, Any]] = {}
APP_SERVER: ThreadingHTTPServer | None = None
WEB_SESSION = {"last_heartbeat": time.monotonic(), "closing": False, "shutdown_started": False}



def set_agent_activity(state: AgentState, task: str, detail: str = "", kind: str = "work", *, history: bool = True) -> None:
    """Publish a concise, user-visible summary of actual autonomous activity."""
    now = now_iso()
    changed = task != state.current_task or detail != state.current_detail
    state.current_task = task
    state.current_detail = str(_auth_redact(detail or ""))[:1200]
    state.last_activity_at = now
    if changed:
        state.task_started_at = now
        if history:
            state.activity_history.append({
                "at": now,
                "kind": kind,
                "task": task,
                "detail": state.current_detail,
            })
            state.activity_history[:] = state.activity_history[-200:]
    try:
        p = project_path(state.project_id)
        write_json(p / ".gameforge" / "live_activity.json", {
            "status": state.status,
            "iteration": state.iteration,
            "task": state.current_task,
            "detail": state.current_detail,
            "task_started_at": state.task_started_at,
            "last_activity_at": state.last_activity_at,
            "history": state.activity_history,
        })
    except Exception:
        pass


def _codex_event_activity(line: str) -> tuple[str, str, str] | None:
    """Convert Codex JSONL events into safe task summaries without exposing reasoning."""
    try:
        event = json.loads(line)
    except Exception:
        return None
    if not isinstance(event, dict):
        return None
    etype = str(event.get("type", "") or "")
    item = event.get("item") if isinstance(event.get("item"), dict) else {}
    itype = str(item.get("type", "") or "")
    joined = (etype + " " + itype).lower()

    command = item.get("command") or event.get("command")
    if command:
        cmd = str(_auth_redact(str(command))).replace("\r", " ").replace("\n", " ").strip()
        return ("Running a computer command", cmd[:900], "command")
    if any(x in joined for x in ("web_search", "search_query", "browser")):
        return ("Researching", "Checking external technical information needed for the current task.", "research")
    if any(x in joined for x in ("file_change", "file_write", "apply_patch", "patch")):
        path_value = item.get("path") or event.get("path") or ""
        detail = ("Updating " + str(path_value)) if path_value else "Editing project files."
        return ("Editing project files", detail[:900], "edit")
    if any(x in joined for x in ("command_execution", "shell", "terminal")):
        return ("Running project tooling", "A build, diagnostic, install, or test command is active.", "command")
    if any(x in joined for x in ("agent_message", "message")):
        text_value = item.get("text") or event.get("text") or ""
        if text_value:
            clean = " ".join(str(text_value).split())
            return ("Reviewing progress", clean[:700], "agent")
        return ("Reviewing progress", "The AI is evaluating the latest project state.", "agent")
    if "reasoning" in joined:
        return ("Analyzing the next step", "The AI is working out what to do next.", "analysis")
    if "turn.started" in etype:
        return ("Starting AI work", "Reading the project state and choosing the next concrete action.", "agent")
    if "turn.completed" in etype:
        return ("Finishing AI work", "The current AI work pass finished; GameForge is moving to verification.", "agent")
    return None


def run_codex_agent_stream(
    args: list[str],
    *,
    cwd: Path,
    input_text: str,
    timeout: int,
    trace_path: Path,
    state: AgentState,
) -> subprocess.CompletedProcess[str]:
    """Run Codex while streaming JSONL into the live task panel and trace file."""
    command, use_shell = _command_invocation("codex", args)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    popen_kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "shell": use_shell,
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "errors": "replace",
        "env": _codex_process_env(),
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(command, **popen_kwargs)
    _bind_active_process(state, proc, "codex")
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    trace_lock = threading.Lock()
    heartbeat_stop = threading.Event()

    def heartbeat() -> None:
        while not heartbeat_stop.wait(2.0):
            if proc.poll() is not None:
                return
            set_agent_activity(state, state.current_task or "Working", state.current_detail, "heartbeat", history=False)

    def read_stdout() -> None:
        if proc.stdout is None:
            return
        with trace_path.open("a", encoding="utf-8", errors="replace", buffering=1) as trace:
            for line in proc.stdout:
                stdout_lines.append(line)
                if len(stdout_lines) > 5000:
                    del stdout_lines[:1000]
                with trace_lock:
                    trace.write(line)
                activity = _codex_event_activity(line)
                if activity:
                    set_agent_activity(state, *activity)

    def read_stderr() -> None:
        if proc.stderr is None:
            return
        for line in proc.stderr:
            stderr_lines.append(line)
            if len(stderr_lines) > 3000:
                del stderr_lines[:500]
            # stderr proves the child is still active even when it is not JSONL.
            state.last_activity_at = now_iso()

    out_thread = threading.Thread(target=read_stdout, daemon=True, name=f"codex-live-out-{state.project_id}")
    err_thread = threading.Thread(target=read_stderr, daemon=True, name=f"codex-live-err-{state.project_id}")
    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True, name=f"codex-live-heartbeat-{state.project_id}")
    out_thread.start(); err_thread.start(); heartbeat_thread.start()
    if proc.stdin is not None:
        proc.stdin.write(input_text)
        proc.stdin.close()
    timed_out = False
    cancelled = False
    deadline = time.time() + timeout
    try:
        while proc.poll() is None:
            if state.stop_event.wait(0.15):
                cancelled = True
                _terminate_process_tree(proc, grace_sec=1.0)
                break
            if time.time() >= deadline:
                timed_out = True
                _terminate_process_tree(proc, grace_sec=1.0)
                break
        try:
            returncode = proc.wait(timeout=3)
        except Exception:
            _terminate_process_tree(proc, grace_sec=0.5)
            returncode = proc.poll() if proc.poll() is not None else -9
        if timed_out:
            raise subprocess.TimeoutExpired(command, timeout, output="".join(stdout_lines), stderr="".join(stderr_lines))
    finally:
        heartbeat_stop.set()
        out_thread.join(timeout=3)
        err_thread.join(timeout=3)
        heartbeat_thread.join(timeout=1)
        if state.active_process is proc:
            _bind_active_process(state, None, "")
    if cancelled:
        stderr_lines.append("\nSTOPPED BY USER\n")
    return subprocess.CompletedProcess(command, returncode, "".join(stdout_lines), "".join(stderr_lines))


def git_checkpoint(p: Path, message: str) -> dict[str, Any]:
    if not command_exists("git"):
        return {"ok": False, "error": "git not installed"}
    subprocess.run(["git", "add", "-A"], cwd=p, capture_output=True)
    proc = subprocess.run(["git", "commit", "-m", message], cwd=p, capture_output=True, text=True)
    rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=p, capture_output=True, text=True)
    return {"ok": proc.returncode == 0 or "nothing to commit" in (proc.stdout + proc.stderr).lower(), "output": proc.stdout + proc.stderr, "rev": rev.stdout.strip()}


def collect_logs(p: Path, cfg: dict[str, Any]) -> str:
    seen: set[Path] = set()
    chunks: list[str] = []
    for pattern in cfg.get("log_globs", []):
        try:
            for f in p.glob(pattern):
                if f.is_file() and f not in seen and f.stat().st_size <= 50_000_000:
                    seen.add(f)
                    chunks.append(f"\n--- {f.relative_to(p)} ---\n{tail_text(f, 12000)}")
        except Exception:
            pass
    cv_report = read_json(p / "captures/metrics.json", None)
    if cv_report:
        chunks.append("\n--- OpenCV visual report ---\n" + json.dumps(cv_report, indent=2))
    return "".join(chunks)[-70000:]


def user_input_request_path(p: Path) -> Path:
    return p / ".gameforge" / "user_input_request.json"

def load_user_input_request(p: Path) -> dict[str, Any] | None:
    req = read_json(user_input_request_path(p), None)
    return req if isinstance(req, dict) and req.get("status", "pending") == "pending" else None

def validate_requested_upload(req: dict[str, Any], filename: str) -> None:
    allowed = [str(x).lower() for x in req.get("accept_extensions", [])]
    if allowed and Path(filename).suffix.lower() not in allowed:
        raise ValueError("Expected file type: " + ", ".join(allowed))

def detect_agent_input_request(p: Path) -> dict[str, Any] | None:
    req = load_user_input_request(p)
    if not req:
        return None
    req.setdefault("id", f"request-{int(time.time())}")
    req.setdefault("kind", "file")
    req.setdefault("title", "GameForge needs input")
    req.setdefault("message", "The autonomous agent needs something only you can provide.")
    req.setdefault("status", "pending")
    write_json(user_input_request_path(p), req)
    return req

def user_review_path(p: Path) -> Path:
    return p / ".gameforge" / "user_review.json"


def load_user_review(p: Path) -> dict[str, Any]:
    data = read_json(user_review_path(p), {}) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("user_done", False)
    data.setdefault("satisfaction", None)
    data.setdefault("feedback", [])
    return data


def save_user_review(p: Path, data: dict[str, Any]) -> dict[str, Any]:
    data["updated_at"] = now_iso()
    write_json(user_review_path(p), data)
    return data


def append_user_feedback(p: Path, text: str, category: str = "general") -> dict[str, Any]:
    review = load_user_review(p)
    feedback = review.setdefault("feedback", [])
    feedback.append({
        "id": f"feedback-{int(time.time() * 1000)}",
        "created_at": now_iso(),
        "category": category or "general",
        "text": text.strip(),
        "addressed": False,
        "status": "pending",
        "ready_for_verification": False,
        "resolution": "",
        "evidence": "",
    })
    return save_user_review(p, review)


def pending_user_feedback(p: Path) -> list[dict[str, Any]]:
    review = load_user_review(p)
    return [
        item for item in review.get("feedback", [])
        if isinstance(item, dict) and not bool(item.get("addressed"))
    ]


def reconcile_feedback_work_orders(
    p: Path,
    before: dict[str, Any],
    build_result: dict[str, Any] | None = None,
    test_result: dict[str, Any] | None = None,
    *,
    verification_complete: bool,
) -> dict[str, Any]:
    """Protect user feedback and only accept agent resolutions backed by verification."""
    review = load_user_review(p)
    current_items = [x for x in review.get("feedback", []) if isinstance(x, dict)]
    before_items = [x for x in before.get("feedback", []) if isinstance(x, dict)]
    before_by_id = {str(x.get("id")): x for x in before_items if x.get("id")}
    current_by_id = {str(x.get("id")): x for x in current_items if x.get("id")}

    # The autonomous agent may update resolution fields, but it may not silently
    # delete or rewrite the user's actual request/category/timestamp.
    for old in before_items:
        feedback_id = str(old.get("id") or "")
        if feedback_id and feedback_id not in current_by_id:
            restored = dict(old)
            current_items.append(restored)
            current_by_id[feedback_id] = restored

    build_failed = bool(build_result and build_result.get("configured") and not build_result.get("ok"))
    test_failed = bool(test_result and test_result.get("configured") and not test_result.get("ok"))
    cfg = read_json(p / "gameforge.json", {}) or {}
    pipeline = iteration_pipeline_settings(cfg)
    strict_quality = bool(pipeline.get("enabled") and pipeline.get("strict_original_quality"))
    build_configured = bool(build_result and build_result.get("configured"))
    test_configured = bool(test_result and test_result.get("configured"))

    for item in current_items:
        feedback_id = str(item.get("id") or "")
        old = before_by_id.get(feedback_id)
        if old:
            for immutable in ("id", "created_at", "category", "text"):
                if immutable in old:
                    item[immutable] = old[immutable]

        was_addressed = bool(old and old.get("addressed"))
        wants_addressed = bool(item.get("addressed"))
        ready_for_verification = bool(item.get("ready_for_verification"))

        if was_addressed:
            # Once verified, keep the work order resolved unless the user creates
            # new feedback describing another change.
            item["addressed"] = True
            item["status"] = "addressed"
            item.setdefault("addressed_at", old.get("addressed_at") or now_iso())
            if old:
                item.setdefault("resolution", old.get("resolution", ""))
                item.setdefault("evidence", old.get("evidence", ""))
            continue

        if wants_addressed or ready_for_verification:
            resolution = str(item.get("resolution", "") or "").strip()
            evidence = str(item.get("evidence", "") or "").strip()
            valid = verification_complete and bool(resolution) and bool(evidence) and not build_failed and not test_failed
            if strict_quality:
                # In strict experimental mode, targeted/savestate/warp/fast-forward
                # checks may guide development but cannot close a user requirement.
                # A successful configured build AND the unchanged configured full
                # regression are mandatory before GameForge closes the work order.
                valid = valid and build_configured and test_configured
            if valid:
                item["addressed"] = True
                item["status"] = "addressed"
                item["ready_for_verification"] = False
                item["addressed_at"] = str(item.get("addressed_at") or now_iso())
                if strict_quality:
                    item["verification_class"] = "targeted-plus-original-full-regression"
                    item["full_regression_verified_at"] = now_iso()
                item.pop("verification_error", None)
            else:
                item["addressed"] = False
                item["status"] = "pending"
                item.pop("addressed_at", None)
                reasons = []
                if not verification_complete:
                    reasons.append("iteration verification did not complete")
                if not resolution:
                    reasons.append("missing resolution summary")
                if not evidence:
                    reasons.append("missing concrete evidence")
                if strict_quality and not build_configured:
                    reasons.append("strict quality requires the configured full build")
                if strict_quality and not test_configured:
                    reasons.append("strict quality requires the configured original full regression")
                if build_failed:
                    reasons.append("configured build failed")
                if test_failed:
                    reasons.append("configured tests failed")
                item["verification_error"] = "; ".join(reasons) or "resolution was not verified"
        else:
            item["addressed"] = False
            item["status"] = "pending"
            item.pop("addressed_at", None)

    review["feedback"] = current_items
    return save_user_review(p, review)


def acceptance_is_complete(p: Path, build_result: dict[str, Any], test_result: dict[str, Any]) -> bool:
    acc = read_json(p / ".gameforge/acceptance.json", {}) or {}
    criteria = acc.get("criteria") or []
    if not acc.get("project_complete") or not criteria:
        return False
    if any(c.get("status") != "pass" or not str(c.get("evidence", "")).strip() for c in criteria):
        return False
    # User feedback is a persistent work-order queue. Technical acceptance alone
    # cannot complete the project while a user-requested change is still pending.
    if pending_user_feedback(p):
        return False
    cfg = read_json(p / "gameforge.json", {}) or {}
    pipeline = iteration_pipeline_settings(cfg)
    strict_quality = bool(pipeline.get("enabled") and pipeline.get("strict_original_quality"))
    if strict_quality and not build_result.get("configured"):
        return False
    if strict_quality and not test_result.get("configured"):
        return False
    if build_result.get("configured") and not build_result.get("ok"):
        return False
    if test_result.get("configured") and not test_result.get("ok"):
        return False
    return True


def build_agent_prompt(p: Path, cfg: dict[str, Any], iteration: int, build_result: dict[str, Any] | None, test_result: dict[str, Any] | None, recovery_context: dict[str, Any] | None = None) -> str:
    pipeline = iteration_pipeline_settings(cfg)
    fast_pipeline = bool(pipeline.get("enabled"))
    review = load_user_review(p)
    if fast_pipeline and pipeline.get("compact_context", True):
        compact = {
            "generated_at": now_iso(),
            "iteration": iteration,
            "goal": str(cfg.get("goal", "")),
            "acceptance": read_json(p / ".gameforge/acceptance.json", {}),
            "user_review": review,
            "last_evidence": read_json(p / ".gameforge/last_evidence.json", {}),
            "last_self_heal": read_json(p / ".gameforge/last_self_heal.json", {}),
            "iteration_notes_tail": tail_text(p / ".gameforge/iteration_notes.md", 14000),
            "git": git_status(p),
        }
        write_json(p / ".gameforge" / "compact_state.json", compact)
        evidence = json.dumps(compact, indent=2, ensure_ascii=False)[-42000:]
    else:
        evidence = collect_logs(p, cfg)
    prior = ""
    feedback_items = [x for x in review.get("feedback", []) if isinstance(x, dict)]
    pending_feedback = [x for x in feedback_items if not bool(x.get("addressed"))]
    if pending_feedback:
        prior += "\nPENDING USER FEEDBACK WORK ORDERS (highest priority; do not silently skip):\n" + json.dumps(pending_feedback[-20:], indent=2)[-18000:]
    addressed_feedback = [x for x in feedback_items if bool(x.get("addressed"))]
    if addressed_feedback:
        prior += "\nRecently addressed user feedback (context only):\n" + json.dumps(addressed_feedback[-8:], indent=2)[-7000:]
    if review.get("satisfaction") is not None:
        prior += f"\nUser satisfaction: {review.get('satisfaction')}/5\n"
    if build_result is not None:
        prior += "\nPrevious build result:\n" + json.dumps({k:v for k,v in build_result.items() if k != "output"}, indent=2) + "\n" + build_result.get("output", "")[-12000:]
    if test_result is not None:
        prior += "\nPrevious test result:\n" + json.dumps({k:v for k,v in test_result.items() if k != "output"}, indent=2) + "\n" + test_result.get("output", "")[-12000:]
    if recovery_context:
        prior += "\nAutomatic recovery context:\n" + json.dumps(recovery_context, indent=2)[-16000:]
    research = cfg.get("research_mode", "deep")
    if fast_pipeline:
        startup = """FAST STRICT PIPELINE: Start with .gameforge/compact_state.json, goal.md, .gameforge/acceptance.json, .gameforge/user_review.json, and Git status/history. Do NOT bulk-read every old log, research file, capture, or the entire source tree on every iteration. Inspect only the source/tests/research needed for the current work, and retrieve older evidence only when it is specifically relevant.

During the AI turn, prefer short targeted tests for the code you are actively changing. Do not rerun the configured full build/regression merely as an end-of-turn ritual because GameForge will run the configured build and ORIGINAL configured full test once after this turn returns. You MAY run the full suite inside the turn when the change is high-risk (save format, camera/player core, collision/damage, scene transition, object loading, input/render hooks), when diagnosing a failure, or when targeted evidence is insufficient.

STRICT ORIGINAL QUALITY MODE: The original configured build/test commands are the trusted quality gate and must not be weakened, replaced, shortened, fast-forwarded, or rewritten merely to make the experiment look faster. Savestates, direct scene warps, test-only state injection, fast-forward, native-save checkpoints, or other shortcuts may be used ONLY as development diagnostics. They are NEVER trusted acceptance evidence and NEVER sufficient to close a user-feedback work order. After a targeted check looks good, keep addressed=false and set ready_for_verification=true with a concrete resolution and targeted evidence; GameForge will close it only after the unchanged configured full build and full regression pass. Final project completion still requires the original full regression path.

When multiple pending user-feedback work orders are closely related, batch them into one coherent milestone and verify them together instead of spending separate iterations on tiny adjacent changes. This changes workflow efficiency only; it does NOT lower acceptance, regression, evidence, user-feedback completion, visual, physics, audio, gameplay, persistence, or polish requirements."""
    else:
        startup = "Read AGENTS.md, goal.md, gameforge.json, .gameforge/acceptance.json, research/, UPLOAD/, the current source tree, and Git history/status before changing anything."
    return f'''You are iteration {iteration} of a persistent autonomous game-development run.\n\n{startup}\n\nResearch mode: {research}. Internet research requested: {cfg.get("internet_research", True)}. If web/internet tools are available, use them when they materially improve correctness or unblock implementation. Prefer primary/official sources and public source code; record important sources/provenance in research/SOURCES.md.\n\nYour job this iteration is to make the highest-value SAFE, REVERSIBLE progress toward the user's playable goal. Implement and debug rather than only describing. Use uploaded assets when useful and adapt them to the target game's native visual/technical style. Never invent unsupported APIs. Preserve known-good behavior.\n\nAfter making changes, update .gameforge/acceptance.json honestly. Do NOT set project_complete=true unless there is concrete runtime/test evidence for every criterion. Leave notes in .gameforge/iteration_notes.md about what changed, what was tested, what remains, and the next best action.

USER FEEDBACK WORK-ORDER CONTRACT: Every entry in .gameforge/user_review.json with addressed=false is a persistent requirement and takes priority over lower-value roadmap polish. Do not merely acknowledge it. Implement the requested change, build/run the relevant result, and verify the user's requested behavior or appearance with concrete evidence. In strict quality mode, after your targeted verification set ready_for_verification=true but keep addressed=false; GameForge itself will mark it addressed only after the configured original full build/regression pass. Outside strict quality mode, only after verification may you update that same feedback entry to addressed=true and status="addressed". When doing so, preserve id/created_at/category/text exactly and add non-empty "resolution" (what changed), "evidence" (specific test/log/capture/runtime proof), and "addressed_at". If verification is incomplete, a configured build/test fails, or the request is blocked, keep addressed=false/status="pending" and explain the blocker in iteration notes. Never delete a feedback entry. GameForge will reject unsupported resolution claims and will not accept project completion while any feedback work order remains pending.

Treat build/runtime warnings, dependency errors, WSL issues, toolchain failures, crashes, missing packages, configuration mistakes, and environment problems as live diagnostic signals. For every recoverable issue: read the exact output, identify the root cause, apply the smallest safe reversible fix, rerun the exact failed step, verify it, and continue toward the playable result. Install missing dependencies autonomously from official package managers or authoritative upstream sources when allowed. Prefer project-local or user-local installs, unattended/non-interactive flags, and pinned/reproducible versions. Never open terminal windows just to run WSL, PowerShell, package managers, compilers, or tests; keep diagnostics and repairs headless and capture their output. In WSL, prefer non-interactive commands and repair filesystem/tool configuration rather than repeatedly tolerating the same warning. Do not ask the user to perform routine debugging, install ordinary development dependencies, copy files between project folders, edit configs, or rerun commands that you can safely do yourself.

Before declaring a blocker, exhaust SAFE, LEGAL, REAL autonomous options: inspect existing project uploads/local files, public/authorized sources, official documentation, and legitimately redistributable dependencies. Never download pirated commercial games/ROMs, leaked credentials, or other unauthorized material. If progress genuinely requires user-only input, DO NOT merely mention the blocker in notes and DO NOT keep burning iterations. Write .gameforge/user_input_request.json and stop the iteration cleanly. Schema:
{{"status":"pending","kind":"file|url|text|choice|confirm","title":"short human title","message":"exactly what is needed and why","why_user_required":"why autonomous acquisition is unavailable/inappropriate","accept_extensions":[".z64"],"upload_category":"ROMS_LOCAL","placeholder":"","choices":[],"resume_after_submit":true}}
For files, list ONLY valid expected extensions. For a copyrighted base ROM, tell the user to provide their own legally obtained copy; never search for unauthorized ROM downloads. For URLs, request a URL only when the user must identify/authorize the source.\n\nRecent evidence from logs/OpenCV/runtime:\n{evidence[-50000:] if evidence else '(none yet)'}\n{prior[-30000:]}\n'''


def agent_loop(project_id: str) -> None:
    state = AGENTS[project_id]
    p = project_path(project_id)
    cfg = project_config(project_id)
    max_iter = int(cfg.get("agent", {}).get("max_iterations", 0) or 0)
    cooldown = float(cfg.get("agent", {}).get("cooldown_sec", 3) or 3)
    timeout = int(cfg.get("command_timeout_sec", 1800) or 1800)
    max_auto_recovery = int(cfg.get("agent", {}).get("max_auto_recovery_attempts", 8) or 8)
    recovery_failures = 0
    recovery_context: dict[str, Any] | None = None
    build_result = test_result = None
    state.status = "running"
    state.started_at = now_iso()
    state.message = "Starting autonomous game-development loop"
    try:
        if not command_exists("codex"):
            state.status = "blocked"
            state.message = "Codex CLI not found. Install it and sign in with your ChatGPT account."
            return
        while not state.stop_event.is_set():
            review = load_user_review(p)
            if review.get("user_done"):
                state.status = "user-complete"
                state.message = "User marked this result done. Reopen it from User Review to continue from this exact state."
                return
            while state.pause_event.is_set() and not state.stop_event.is_set():
                state.status = "paused"
                time.sleep(0.5)
            if state.stop_event.is_set():
                break
            state.status = "running"

            # A local "login status" is insufficient: affected Codex builds can
            # report logged in yet send Responses requests with no Authorization
            # header. Verify the real request path before consuming an iteration.
            # Run this before incrementing so a failed auth check remains iteration 0.
            set_agent_activity(state, "Checking AI runtime", "Verifying Codex authentication and inference before starting this iteration.", "check")
            auth_check = codex_auth_preflight(p)
            if not auth_check.get("ok"):
                state.status = "blocked"
                state.message = auth_check.get("message", "Codex authentication preflight failed")
                RUNTIME_STATE["codex_login_message"] = state.message
                return

            state.iteration += 1
            if max_iter and state.iteration > max_iter:
                state.status = "paused"
                state.message = f"Reached configured max_iterations={max_iter}"
                return

            iteration = state.iteration
            state.last_update = now_iso()
            state.message = f"Iteration {iteration}: checkpointing and asking Codex to improve the playable result"
            set_agent_activity(state, "Saving a safety checkpoint", f"Creating the pre-iteration Git checkpoint for iteration {iteration}.", "checkpoint")
            git_checkpoint(p, f"GameForge pre-iteration {iteration}")
            review_before_iteration = load_user_review(p)
            prompt = build_agent_prompt(p, cfg, iteration, build_result, test_result, recovery_context)
            trace_path = p / f"logs/codex-iteration-{iteration:04d}.jsonl"
            final_path = p / f"logs/codex-iteration-{iteration:04d}.final.txt"
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            codex_args = ["exec", "--json", "--skip-git-repo-check"]
            permission_mode = cfg.get("agent", {}).get("permission_mode", "full-auto")
            if permission_mode == "full-auto":
                # Codex 0.159.x can reject PowerShell itself under the Windows
                # workspace-write execution policy even when approval_policy=never.
                # GameForge full-auto explicitly means the autonomous project agent
                # may run project-local shell/build/test tooling without prompts.
                codex_args += ["--dangerously-bypass-approvals-and-sandbox"]
            else:
                codex_args += ["--sandbox", "workspace-write"]
            auth_trace("agent_codex_exec", project=str(p), iteration=iteration,
                       permission_mode=permission_mode, codex_args=codex_args)
            # "-" forces Codex to read the prompt from stdin. This avoids Windows
            # npm .cmd shim execution issues and command-line length limits.
            codex_args.append("-")
            started = time.time()
            try:
                trace_path.write_text("", encoding="utf-8")
                set_agent_activity(state, "AI is working on the project", "Codex is reading, editing, diagnosing, building, or testing. Live command activity will appear here.", "agent")
                proc = run_codex_agent_stream(
                    codex_args,
                    cwd=p,
                    input_text=prompt,
                    timeout=max(timeout, 3600),
                    trace_path=trace_path,
                    state=state,
                )
                final_path.write_text((proc.stderr or "")[-120000:], encoding="utf-8")
                if state.stop_event.is_set():
                    reconcile_feedback_work_orders(
                        p, review_before_iteration, verification_complete=False
                    )
                    state.status = "stopped"
                    state.message = "Stopped by user; active Codex work was interrupted and project state was preserved."
                    set_agent_activity(state, "Stopped", state.message, "stopped")
                    return
                pending_input = detect_agent_input_request(p)
                if pending_input:
                    reconcile_feedback_work_orders(
                        p, review_before_iteration, verification_complete=False
                    )
                    state.status = "waiting_for_user"
                    state.message = pending_input.get("message") or "Waiting for required user input"
                    set_agent_activity(state, "Waiting for your input", state.message, "waiting")
                    state.input_request = pending_input
                    return
                if proc.returncode != 0:
                    reconcile_feedback_work_orders(
                        p, review_before_iteration, verification_complete=False
                    )
                    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
                    lower = combined.lower()
                    if "401 unauthorized" in lower:
                        state.status = "blocked"
                        state.message = "Codex authentication was rejected (401). Project state is preserved; sign in again, then Resume."
                        RUNTIME_STATE["codex_login_message"] = "Codex request rejected (401); re-authentication may be required."
                        return
                    if any(x in lower for x in ["usage limit", "rate limit", "sign in", "login", "authentication"]):
                        state.status = "blocked"
                        state.message = "Codex stopped for authentication or service availability. Project state is preserved; resume after access is restored."
                        return

                    recovery_failures += 1
                    recovery_context = {
                        "kind": "codex_process_failure",
                        "attempt": recovery_failures,
                        "max_attempts": max_auto_recovery,
                        "exit_code": proc.returncode,
                        "output_tail": combined[-12000:],
                        "instruction": "Diagnose and repair this automatically, rerun the failed operation, verify the fix, then continue the project.",
                    }
                    write_json(p / ".gameforge" / "last_self_heal.json", {
                        "timestamp": now_iso(),
                        "iteration": iteration,
                        **recovery_context,
                    })

                    if any(x in lower for x in ["node\" is not recognized", "'node' is not recognized", "node: command not found", "env: node: no such file"]):
                        state.status = "self-healing"
                        state.message = "Codex runtime dependency failed; repairing the official Codex installation automatically"
                        repair = install_codex(force=True)
                        recovery_context["runtime_repair"] = repair
                        if repair.get("ok"):
                            if state.stop_event.wait(min(cooldown, 3)):
                                return
                            continue

                    if recovery_failures < max_auto_recovery:
                        state.status = "self-healing"
                        state.message = f"Iteration {iteration} hit a recoverable tooling/runtime failure; auto-diagnosing and retrying ({recovery_failures}/{max_auto_recovery})"
                        git_checkpoint(p, f"GameForge self-heal checkpoint {iteration}")
                        if state.stop_event.wait(min(30.0, max(cooldown, recovery_failures * 2.0))):
                            return
                        continue

                    state.status = "blocked"
                    state.message = f"Automatic recovery tried {recovery_failures} times without restoring the Codex/tooling path. Project state and diagnostics are preserved."
                    return

                recovery_failures = 0
                recovery_context = None
            except subprocess.TimeoutExpired as exc:
                reconcile_feedback_work_orders(
                    p, review_before_iteration, verification_complete=False
                )
                recovery_failures += 1
                recovery_context = {
                    "kind": "codex_timeout",
                    "attempt": recovery_failures,
                    "max_attempts": max_auto_recovery,
                    "timeout_sec": max(timeout, 3600),
                    "output_tail": ((exc.stdout or "") + "\n" + (exc.stderr or ""))[-12000:],
                    "instruction": "Determine why the previous autonomous step hung, use a non-interactive/headless alternative, verify it, and continue.",
                }
                write_json(p / ".gameforge" / "last_self_heal.json", {
                    "timestamp": now_iso(),
                    "iteration": iteration,
                    **recovery_context,
                })
                if recovery_failures < max_auto_recovery:
                    state.status = "self-healing"
                    state.message = f"Iteration {iteration} timed out; automatically diagnosing and retrying ({recovery_failures}/{max_auto_recovery})"
                    if state.stop_event.wait(min(30.0, max(cooldown, recovery_failures * 2.0))):
                        return
                    continue
                state.status = "blocked"
                state.message = f"Automatic recovery exhausted {recovery_failures} timeout attempts. Project state and diagnostics are preserved."
                return

            if load_user_review(p).get("user_done"):
                reconcile_feedback_work_orders(
                    p, review_before_iteration, verification_complete=False
                )
                git_checkpoint(p, f"GameForge user-marked done after iteration {iteration}")
                state.status = "user-complete"
                state.message = "User marked this result done. Current work is checkpointed; reopen it to continue from here."
                return

            cfg = project_config(project_id)  # reload in case commands changed
            commands = cfg.get("commands", {})
            state.message = f"Iteration {iteration}: running configured build"
            set_agent_activity(state, "Building the project", commands.get("build", "") or "No custom build command is configured; verifying build state.", "build")
            build_result = run_shell(commands.get("build", ""), p, timeout, p / f"logs/build-{iteration:04d}.log", activity_state=state)
            if state.stop_event.is_set():
                state.status = "stopped"
                state.message = "Stopped by user during build; project state preserved."
                set_agent_activity(state, "Stopped", state.message, "stopped")
                return
            state.message = f"Iteration {iteration}: running configured tests"
            set_agent_activity(state, "Running tests", commands.get("test", "") or "No custom test command is configured; verifying available evidence.", "test")
            test_result = run_shell(commands.get("test", ""), p, timeout, p / f"logs/test-{iteration:04d}.log", activity_state=state)
            if state.stop_event.is_set():
                reconcile_feedback_work_orders(
                    p, review_before_iteration, build_result, test_result, verification_complete=False
                )
                state.status = "stopped"
                state.message = "Stopped by user during test; project state preserved."
                set_agent_activity(state, "Stopped", state.message, "stopped")
                return

            review_after_verification = reconcile_feedback_work_orders(
                p,
                review_before_iteration,
                build_result,
                test_result,
                verification_complete=True,
            )
            pending_feedback_count = sum(
                1 for item in review_after_verification.get("feedback", [])
                if isinstance(item, dict) and not bool(item.get("addressed"))
            )

            failed_steps = []
            if build_result.get("configured") and not build_result.get("ok"):
                failed_steps.append({"step": "build", "exit_code": build_result.get("exit_code"), "output_tail": build_result.get("output", "")[-12000:]})
            if test_result.get("configured") and not test_result.get("ok"):
                failed_steps.append({"step": "test", "exit_code": test_result.get("exit_code"), "output_tail": test_result.get("output", "")[-12000:]})
            if failed_steps:
                recovery_context = {
                    "kind": "build_or_test_failure",
                    "attempt": 1,
                    "failed_steps": failed_steps,
                    "instruction": "Diagnose each failure from the exact output, repair it safely, rerun the failed step, verify it passes, then continue.",
                }
                write_json(p / ".gameforge" / "last_self_heal.json", {
                    "timestamp": now_iso(),
                    "iteration": iteration,
                    **recovery_context,
                })
                state.status = "self-healing"
                state.message = f"Iteration {iteration}: build/test evidence found a recoverable failure; continuing into automatic diagnosis"
            else:
                recovery_context = None

            evidence = {
                "iteration": iteration,
                "timestamp": now_iso(),
                "codex_duration_sec": round(time.time() - started, 2),
                "build": {k:v for k,v in build_result.items() if k != "output"},
                "test": {k:v for k,v in test_result.items() if k != "output"},
                "visual": read_json(p / "captures/metrics.json", {}),
                "pending_user_feedback": pending_feedback_count,
            }
            write_json(p / ".gameforge/last_evidence.json", evidence)

            if acceptance_is_complete(p, build_result, test_result):
                git_checkpoint(p, f"GameForge verified completion iteration {iteration}")
                state.status = "complete"
                state.message = "Acceptance criteria are marked complete with evidence and configured build/tests pass."
                set_agent_activity(state, "Project verified complete", state.message, "complete")
                return

            git_checkpoint(p, f"GameForge iteration {iteration} progress")
            state.last_update = now_iso()
            if pending_feedback_count:
                state.message = f"Iteration {iteration} incomplete; {pending_feedback_count} user feedback work order(s) still pending"
            else:
                state.message = f"Iteration {iteration} incomplete; continuing after evidence/regression checks"
            set_agent_activity(state, "Preparing the next improvement pass", state.message, "loop")
            if state.stop_event.wait(cooldown):
                return
    except Exception as exc:
        state.status = "error"
        state.message = f"{exc}\n{traceback.format_exc()[-4000:]}"
    finally:
        if state.stop_event.is_set() and state.status not in {"complete", "error"}:
            state.status = "stopped"
            state.message = "Stopped by user; project state preserved."
        state.last_update = now_iso()


def start_agent(project_id: str) -> dict[str, Any]:
    project_config(project_id)
    with STATE_LOCK:
        existing = AGENTS.get(project_id)
        if existing and existing.thread and existing.thread.is_alive():
            existing.pause_event.clear()
            return agent_public(existing)
        state = AgentState(project_id=project_id)
        AGENTS[project_id] = state
        t = threading.Thread(target=agent_loop, args=(project_id,), daemon=True, name=f"agent-{project_id}")
        state.thread = t
        t.start()
        return agent_public(state)


def agent_public(s: AgentState) -> dict[str, Any]:
    return {
        "project_id": s.project_id,
        "status": s.status,
        "iteration": s.iteration,
        "message": s.message,
        "started_at": s.started_at,
        "last_update": s.last_update,
        "stop_requested": s.stop_event.is_set(),
        "active_process": {
            "kind": s.active_process_kind,
            "pid": s.active_process.pid if s.active_process and s.active_process.poll() is None else None,
            "started_at": s.active_process_started_at,
        },
        "activity": {
            "task": s.current_task,
            "detail": s.current_detail,
            "task_started_at": s.task_started_at,
            "last_activity_at": s.last_activity_at,
            "history": s.activity_history[-100:],
        },
    }


def cv_loop(project_id: str) -> None:
    s = CVS[project_id]
    p = project_path(project_id)
    cfg = project_config(project_id).get("visual", {})
    try:
        import cv2  # type: ignore
        import mss  # type: ignore
        import numpy as np  # type: ignore
    except Exception as exc:
        s.status = "blocked"
        s.message = f"OpenCV capture dependencies unavailable: {exc}. Run setup again."
        return
    s.status = "running"
    interval = max(0.2, float(cfg.get("interval_sec", 1.0)))
    freeze_seconds = max(2, int(cfg.get("freeze_seconds", 8)))
    black_threshold = float(cfg.get("black_mean_threshold", 8.0))
    monitor_index = int(cfg.get("monitor", 1))
    region = cfg.get("region")
    prev_gray = None
    freeze_start = None
    captures = p / "captures"
    captures.mkdir(exist_ok=True)
    try:
        with mss.mss() as sct:
            if monitor_index >= len(sct.monitors):
                monitor_index = 1 if len(sct.monitors) > 1 else 0
            monitor = dict(sct.monitors[monitor_index])
            window_title = str(cfg.get("window_title", "") or "").strip()
            if window_title and os.name == "nt":
                try:
                    import pygetwindow as gw  # type: ignore
                    wins = [w for w in gw.getWindowsWithTitle(window_title) if getattr(w, "width", 0) > 20 and getattr(w, "height", 0) > 20]
                    if wins:
                        w = wins[0]
                        monitor = {"left": int(w.left), "top": int(w.top), "width": int(w.width), "height": int(w.height)}
                except Exception as exc:
                    s.message = f"Window targeting fallback to monitor capture: {exc}"
            if isinstance(region, dict) and all(k in region for k in ("left", "top", "width", "height")):
                monitor = {k:int(region[k]) for k in ("left", "top", "width", "height")}
            while not s.stop_event.is_set():
                frame = np.array(sct.grab(monitor))
                bgr = frame[:, :, :3]
                gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                mean = float(gray.mean())
                std = float(gray.std())
                diff_mean = None
                frozen = False
                if prev_gray is not None and prev_gray.shape == gray.shape:
                    diff_mean = float(cv2.absdiff(gray, prev_gray).mean())
                    if diff_mean < 0.8:
                        if freeze_start is None:
                            freeze_start = time.time()
                        frozen = (time.time() - freeze_start) >= freeze_seconds
                    else:
                        freeze_start = None
                prev_gray = gray
                black = mean < black_threshold and std < 12
                cv2.imwrite(str(captures / "latest.jpg"), bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                metrics = {
                    "timestamp": now_iso(),
                    "monitor": monitor_index,
                    "region": monitor,
                    "mean_brightness": round(mean, 3),
                    "contrast_std": round(std, 3),
                    "frame_diff_mean": None if diff_mean is None else round(diff_mean, 3),
                    "black_screen_suspected": black,
                    "frozen_screen_suspected": frozen,
                    "note": "Visual smoke-test metrics only. Project-specific detectors/tests should be added for HUD/objectives/mission states.",
                }
                write_json(captures / "metrics.json", metrics)
                s.message = "Capturing game/display frames and OpenCV smoke-test metrics"
                time.sleep(interval)
    except Exception as exc:
        s.status = "error"
        s.message = f"OpenCV monitor error: {exc}"
        return
    s.status = "stopped"
    s.message = "Visual monitor stopped"


def start_cv(project_id: str) -> dict[str, Any]:
    project_config(project_id)
    existing = CVS.get(project_id)
    if existing and existing.thread and existing.thread.is_alive():
        return {"status": existing.status, "message": existing.message}
    s = CVState(project_id=project_id)
    CVS[project_id] = s
    t = threading.Thread(target=cv_loop, args=(project_id,), daemon=True, name=f"cv-{project_id}")
    s.thread = t
    t.start()
    return {"status": "starting", "message": "Starting OpenCV monitor"}


def scan_uploads(project_id: str) -> dict[str, Any]:
    p = project_path(project_id)
    base = p / "UPLOAD"
    items = []
    license_names = {"license", "license.txt", "license.md", "copying", "copying.txt"}
    for f in sorted(base.rglob("*")):
        if not f.is_file() or f.name == ".gitkeep":
            continue
        try:
            h = hashlib.sha256()
            with f.open("rb") as fh:
                while True:
                    chunk = fh.read(1024 * 1024)
                    if not chunk: break
                    h.update(chunk)
            ext = f.suffix.lower()
            category = f.relative_to(base).parts[0] if len(f.relative_to(base).parts) > 1 else "ROOT"
            items.append({
                "path": str(f.relative_to(p)).replace("\\", "/"),
                "category": category,
                "bytes": f.stat().st_size,
                "sha256": h.hexdigest(),
                "extension": ext,
                "license_file": f.name.lower() in license_names,
            })
        except Exception as exc:
            items.append({"path": str(f.relative_to(p)), "error": str(exc)})
    manifest = {"scanned_at": now_iso(), "count": len(items), "items": items}
    write_json(p / ".gameforge/upload_manifest.json", manifest)
    return manifest



def list_processes(limit: int = 300) -> list[dict[str, Any]]:
    try:
        import psutil  # type: ignore
    except Exception:
        return []
    rows = []
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "create_time"]):
        try:
            info = proc.info
            rows.append({
                "pid": info.get("pid"),
                "name": info.get("name") or "",
                "exe": info.get("exe") or "",
                "cmdline": " ".join(info.get("cmdline") or [])[:800],
                "create_time": info.get("create_time"),
            })
        except Exception:
            continue
    rows.sort(key=lambda x: (x.get("name") or "").lower())
    return rows[:limit]


def managed_process_public(project_id: str) -> dict[str, Any]:
    proc = MANAGED_PROCESSES.get(project_id)
    meta = dict(MANAGED_PROCESS_META.get(project_id, {}))
    if not proc:
        return {"running": False, **meta}
    rc = proc.poll()
    meta.update({"running": rc is None, "pid": proc.pid, "returncode": rc})
    return meta


def start_managed_process(project_id: str, command: str | None = None) -> dict[str, Any]:
    p = project_path(project_id)
    cfg = project_config(project_id)
    command = (command or cfg.get("commands", {}).get("launch", "")).strip()
    if not command:
        return {"ok": False, "error": "No launch command configured"}
    old = MANAGED_PROCESSES.get(project_id)
    if old and old.poll() is None:
        return {"ok": True, **managed_process_public(project_id)}
    log_path = p / "logs" / f"managed-launch-{int(time.time())}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("a", encoding="utf-8", errors="replace")
    kwargs: dict[str, Any] = {"cwd": str(p), "shell": True, "stdout": log_handle, "stderr": subprocess.STDOUT, "text": True}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(command, **kwargs)
    MANAGED_PROCESSES[project_id] = proc
    MANAGED_PROCESS_META[project_id] = {"command": command, "started_at": now_iso(), "log": str(log_path.relative_to(p)).replace("\\", "/")}
    return {"ok": True, **managed_process_public(project_id)}


def stop_managed_process(project_id: str) -> dict[str, Any]:
    proc = MANAGED_PROCESSES.get(project_id)
    if not proc or proc.poll() is not None:
        return {"ok": True, **managed_process_public(project_id)}
    try:
        if os.name == "nt":
            # Managed Windows processes are created in their own process group.
            # Ask them to stop cleanly first so editors/build tools can flush data.
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
                proc.wait(timeout=8)
            except Exception:
                # Escalate only after the graceful request times out.
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    except Exception as exc:
        return {"ok": False, "error": str(exc), **managed_process_public(project_id)}
    return {"ok": True, **managed_process_public(project_id)}


def git_status(p: Path) -> dict[str, Any]:
    if not command_exists("git") or not (p / ".git").exists():
        return {"ok": False, "error": "Git repository unavailable"}
    st = subprocess.run(["git", "status", "--short"], cwd=p, capture_output=True, text=True)
    lg = subprocess.run(["git", "log", "--oneline", "-12"], cwd=p, capture_output=True, text=True)
    rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=p, capture_output=True, text=True)
    return {"ok": True, "status": st.stdout, "log": lg.stdout, "head": rev.stdout.strip()}


def git_rollback(p: Path, revision: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", revision or ""):
        return {"ok": False, "error": "Invalid revision"}
    before = git_checkpoint(p, "GameForge pre-rollback safety checkpoint")
    proc = subprocess.run(["git", "reset", "--hard", revision], cwd=p, capture_output=True, text=True)
    return {"ok": proc.returncode == 0, "output": proc.stdout + proc.stderr, "safety_checkpoint": before}


def run_input_sequence(project_id: str, sequence: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        from pynput import keyboard, mouse  # type: ignore
    except Exception as exc:
        return {"ok": False, "error": f"Input automation unavailable: {exc}"}

    if len(sequence) > 500:
        return {"ok": False, "error": "Sequence too long"}

    kb = keyboard.Controller()
    ms = mouse.Controller()

    special_keys = {
        "enter": keyboard.Key.enter, "return": keyboard.Key.enter,
        "esc": keyboard.Key.esc, "escape": keyboard.Key.esc,
        "space": keyboard.Key.space, "tab": keyboard.Key.tab,
        "shift": keyboard.Key.shift, "ctrl": keyboard.Key.ctrl,
        "control": keyboard.Key.ctrl, "alt": keyboard.Key.alt,
        "backspace": keyboard.Key.backspace, "delete": keyboard.Key.delete,
        "up": keyboard.Key.up, "down": keyboard.Key.down,
        "left": keyboard.Key.left, "right": keyboard.Key.right,
        "home": keyboard.Key.home, "end": keyboard.Key.end,
        "pageup": keyboard.Key.page_up, "pagedown": keyboard.Key.page_down,
    }
    for i in range(1, 13):
        special_keys[f"f{i}"] = getattr(keyboard.Key, f"f{i}")

    buttons = {
        "left": mouse.Button.left,
        "right": mouse.Button.right,
        "middle": mouse.Button.middle,
    }

    def key_for(raw: Any):
        name = str(raw or "").strip().lower()
        if name in special_keys:
            return special_keys[name]
        if len(name) == 1:
            return name
        raise ValueError(f"Unsupported key: {raw}")

    events = []
    for step in sequence:
        kind = str(step.get("type", "")).lower()
        delay = min(30.0, max(0.0, float(step.get("delay", 0))))
        if delay:
            time.sleep(delay)
        try:
            if kind == "key":
                kb.press(key_for(step.get("key")))
                kb.release(key_for(step.get("key")))
            elif kind == "keydown":
                kb.press(key_for(step.get("key")))
            elif kind == "keyup":
                kb.release(key_for(step.get("key")))
            elif kind == "click":
                button = buttons.get(str(step.get("button", "left")).lower())
                if button is None:
                    raise ValueError("Unsupported mouse button")
                ms.click(button, int(step.get("count", 1) or 1))
            elif kind == "move":
                x = int(step.get("x", 0))
                y = int(step.get("y", 0))
                duration = min(2.0, max(0.0, float(step.get("duration", 0))))
                if duration <= 0:
                    ms.move(x, y)
                else:
                    steps = max(1, int(duration * 60))
                    sx, sy = x / steps, y / steps
                    for _ in range(steps):
                        ms.move(int(round(sx)), int(round(sy)))
                        time.sleep(duration / steps)
            elif kind == "sleep":
                time.sleep(min(30.0, max(0.0, float(step.get("seconds", 1)))))
            else:
                events.append({"step": step, "ok": False, "error": "unknown input type"})
                continue
            events.append({"step": step, "ok": True})
        except Exception as exc:
            events.append({"step": step, "ok": False, "error": str(exc)})
            break

    out = {"ok": all(e.get("ok") for e in events), "ran_at": now_iso(), "events": events}
    write_json(project_path(project_id) / ".gameforge" / "last_input_replay.json", out)
    return out


def run_research_task(project_id: str, question: str) -> dict[str, Any]:
    p = project_path(project_id)
    cfg = project_config(project_id)
    if not command_exists("codex"):
        return {"ok": False, "error": "Codex CLI unavailable"}
    prompt = f'''You are the dedicated GameForge research agent for this playable game-development project.
Read goal.md, AGENTS.md, UPLOAD/, research/, and the source tree.
Research depth: {cfg.get("research_mode", "deep")}. Internet research requested: {cfg.get("internet_research", True)}.
Question/task: {question}

Research broadly but use only public/authorized sources. Prioritize official/primary sources, public source repositories, archived developer materials, interviews, issue trackers, modding documentation, public reverse-engineering research, and technically relevant historical material. Separate VERIFIED facts, developer statements, reported/cut concepts, community theory, and project-original conclusions. Record URLs/titles/provenance in research/SOURCES.md and write a concise actionable synthesis to research/LATEST_RESEARCH.md. Do not modify gameplay code in this research task.'''
    proc = run_codex(
        ["exec", "--json", "-"],
        cwd=p,
        input_text=prompt,
        timeout=max(3600, int(cfg.get("command_timeout_sec", 1800))),
    )
    log = p / "logs" / f"research-{int(time.time())}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text((proc.stdout or "") + "\n" + (proc.stderr or ""), encoding="utf-8")
    return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "log": str(log.relative_to(p)).replace("\\", "/"), "output": ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-30000:]}


def analyze_assets(project_id: str) -> dict[str, Any]:
    p = project_path(project_id)
    base = p / "UPLOAD"
    items = []
    image_ext = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".webp"}
    model_ext = {".obj", ".fbx", ".gltf", ".glb", ".blend", ".dae", ".stl"}
    for f in base.rglob("*"):
        if not f.is_file() or f.name == ".gitkeep": continue
        row = {"path": str(f.relative_to(p)).replace("\\", "/"), "bytes": f.stat().st_size, "extension": f.suffix.lower()}
        if f.suffix.lower() in image_ext:
            try:
                import cv2  # type: ignore
                im = cv2.imread(str(f))
                if im is not None: row.update({"kind": "image", "width": int(im.shape[1]), "height": int(im.shape[0]), "channels": int(im.shape[2]) if len(im.shape)>2 else 1})
            except Exception: pass
        elif f.suffix.lower() == ".obj":
            try:
                v=vt=vn=faces=0
                with f.open("r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        if line.startswith("v "): v+=1
                        elif line.startswith("vt "): vt+=1
                        elif line.startswith("vn "): vn+=1
                        elif line.startswith("f "): faces+=1
                row.update({"kind":"model", "vertices":v, "faces":faces, "uvs":vt, "normals":vn})
            except Exception: pass
        elif f.suffix.lower() in model_ext:
            row["kind"]="model"
        items.append(row)
    report={"analyzed_at":now_iso(),"count":len(items),"items":items}
    write_json(p/".gameforge"/"asset_analysis.json", report)
    return report

def system_status() -> dict[str, Any]:
    codex_ver = ""
    codex_ok = False
    codex_error = ""
    codex_path = resolve_command("codex") or ""
    if codex_path:
        try:
            proc = run_codex(["--version"], timeout=10)
            codex_ver = (proc.stdout or proc.stderr or "").strip()
            codex_ok = proc.returncode == 0
            if not codex_ok:
                codex_error = f"Codex --version exited with {proc.returncode}"
        except Exception as exc:
            codex_error = str(exc)
    deps = {}
    for name in ["cv2", "mss", "psutil"]:
        try:
            __import__(name)
            deps[name] = True
        except Exception:
            deps[name] = False
    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "git": command_exists("git"),
        "codex": codex_ok,
        "codex_path": codex_path,
        "codex_version": codex_ver,
        "codex_error": codex_error,
        "codex_installing": bool(RUNTIME_STATE["codex_installing"]),
        "codex_install_message": RUNTIME_STATE["codex_install_message"],
        "codex_install_error": RUNTIME_STATE["codex_install_error"],
        "codex_login_in_progress": bool(RUNTIME_STATE.get("codex_login_in_progress")),
        "codex_login_message": RUNTIME_STATE.get("codex_login_message", ""),
        "codex_config": _codex_config_diagnostics(),
        "codex_auth": codex_auth_status() if codex_ok else {"available": codex_ok, "authenticated": False, "message": "Codex install required"},
        "opencv": deps["cv2"],
        "mss": deps["mss"],
        "psutil": deps["psutil"],
        "hostname": socket.gethostname(),
    }


def graceful_session_shutdown(reason: str = "web-ui-closed") -> dict[str, Any]:
    """Checkpoint/pause project work and stop child runtime processes before exit."""
    if WEB_SESSION.get("shutdown_started"):
        return {"ok": True, "already_started": True}
    WEB_SESSION["shutdown_started"] = True
    report: dict[str, Any] = {"ok": True, "reason": reason, "projects": {}}
    project_ids = set(AGENTS) | set(CVS) | set(MANAGED_PROCESSES)
    for pid in project_ids:
        item: dict[str, Any] = {}
        try:
            p = project_path(pid)
            agent = AGENTS.get(pid)
            cv = CVS.get(pid)
            proc_meta = MANAGED_PROCESS_META.get(pid, {})
            resume = {
                "saved_at": now_iso(),
                "reason": reason,
                "agent_was_running": bool(agent and agent.thread and agent.thread.is_alive() and agent.status == "running"),
                "agent_iteration": agent.iteration if agent else 0,
                "cv_was_running": bool(cv and cv.thread and cv.thread.is_alive() and cv.status == "running"),
                "managed_process_command": proc_meta.get("command", ""),
            }
            write_json(p / ".gameforge" / "resume-session.json", resume)
            if agent and agent.thread and agent.thread.is_alive():
                agent.pause_event.set()
                agent.status = "paused"
                agent.message = "Paused safely because the GameForge web UI closed"
            if cv:
                cv.stop_event.set()
            if MANAGED_PROCESSES.get(pid) and MANAGED_PROCESSES[pid].poll() is None:
                item["process"] = stop_managed_process(pid)
            item["checkpoint"] = git_checkpoint(p, "GameForge safe checkpoint on UI exit")
            item["resume"] = resume
        except Exception as exc:
            item["error"] = str(exc)
            report["ok"] = False
        report["projects"][pid] = item
    write_json(USER_DATA / "last_shutdown.json", report)
    return report


def _schedule_web_close_shutdown() -> None:
    """Give reload/navigation a grace period; a resumed heartbeat cancels exit."""
    def worker() -> None:
        time.sleep(4.0)
        if not WEB_SESSION.get("closing") or WEB_SESSION.get("shutdown_started"):
            return
        graceful_session_shutdown("web-ui-closed")
        server = APP_SERVER
        if server:
            threading.Thread(target=server.shutdown, daemon=True, name="server-shutdown").start()
    threading.Thread(target=worker, daemon=True, name="web-close-grace").start()


class Handler(SimpleHTTPRequestHandler):
    server_version = "GameForgeAI/1.0-singlefile"

    def log_message(self, fmt: str, *args: Any) -> None:
        with (GLOBAL_LOGS / "server.log").open("a", encoding="utf-8") as f:
            f.write(f"[{now_iso()}] {self.address_string()} {fmt % args}\n")

    def send_json(self, data: Any, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 20_000_000:
            raise ValueError("JSON body too large")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/api/status":
                return self.send_json(system_status())
            if path == "/api/projects":
                projects = []
                seen: set[str] = set()
                roots: list[tuple[str, Path]] = []
                for d in sorted(PROJECTS.iterdir()):
                    if d.is_dir() and (d / "gameforge.json").exists():
                        roots.append((d.name, d))
                for pid, raw in load_project_registry().items():
                    p = Path(raw).expanduser()
                    if p.exists() and (p / "gameforge.json").exists():
                        roots.append((pid, p))
                for pid_hint, d in roots:
                    cfg = read_json(d / "gameforge.json", {})
                    pid = slugify(cfg.get("id") or pid_hint)
                    if pid in seen:
                        continue
                    seen.add(pid)
                    st = AGENTS.get(pid)
                    cfg["id"] = pid
                    cfg["project_root"] = str(d.resolve())
                    cfg["gfai_files"] = [x.name for x in d.glob("*.gfai")]
                    cfg["agent_status"] = agent_public(st) if st else {"status": "idle", "iteration": 0, "message": ""}
                    cfg["acceptance"] = read_json(d / ".gameforge/acceptance.json", {})
                    projects.append(cfg)
                return self.send_json({"projects": projects})
            if path.startswith("/api/project/") and path.endswith("/state"):
                pid = path.split("/")[3]
                p = project_path(pid)
                cfg = project_config(pid)
                st = AGENTS.get(pid)
                cv = CVS.get(pid)
                return self.send_json({
                    "config": cfg,
                    "acceptance": read_json(p / ".gameforge/acceptance.json", {}),
                    "user_review": load_user_review(p),
                    "evidence": read_json(p / ".gameforge/last_evidence.json", {}),
                    "uploads": read_json(p / ".gameforge/upload_manifest.json", {"count": 0, "items": []}),
                    "agent": agent_public(st) if st else {"status":"idle","iteration":0,"message":""},
                    "input_request": load_user_input_request(p),
                    "cv": {"status": cv.status, "message": cv.message} if cv else {"status":"idle","message":""},
                    "visual": read_json(p / "captures/metrics.json", {}),
                    "managed_process": managed_process_public(pid),
                    "assets": read_json(p / ".gameforge/asset_analysis.json", {"count":0,"items":[]}),
                    "git": git_status(p),
                    "experiment": experiment_status(p),
                })
            if path.startswith("/api/project/") and path.endswith("/index"):
                pid = path.split("/")[3]
                p = project_path(pid)
                project_config(pid)
                return self.send_json(scan_project_tree(p))
            if path.startswith("/api/project/") and path.endswith("/processes"):
                pid = path.split("/")[3]
                project_config(pid)
                return self.send_json({"processes": list_processes()})
            if path.startswith("/api/project/") and path.endswith("/logs"):
                pid = path.split("/")[3]
                p = project_path(pid)
                files = []
                for f in sorted((p / "logs").glob("*"), key=lambda x:x.stat().st_mtime if x.exists() else 0, reverse=True)[:30]:
                    if f.is_file():
                        files.append({"name": f.name, "text": tail_text(f, 18000)})
                return self.send_json({"files": files})
            if path.startswith("/api/project/") and path.endswith("/capture.jpg"):
                pid = path.split("/")[3]
                f = project_path(pid) / "captures/latest.jpg"
                if not f.exists():
                    return self.send_error(404)
                data = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers(); self.wfile.write(data); return
        except FileNotFoundError:
            return self.send_json({"error":"project not found"}, 404)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 500)

        # static
        rel = path.lstrip("/") or "index.html"
        f = safe_child(WEB, rel)
        if f.is_dir(): f = f / "index.html"
        if not f.exists() or not f.is_file():
            f = WEB / "index.html"
        data = f.read_bytes()
        mime = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(data)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/session/heartbeat":
                WEB_SESSION["last_heartbeat"] = time.monotonic()
                WEB_SESSION["closing"] = False
                return self.send_json({"ok": True})
            if path == "/api/session/closing":
                WEB_SESSION["closing"] = True
                _schedule_web_close_shutdown()
                return self.send_json({"ok": True, "grace_seconds": 4})
            if path == "/api/codex/install":
                return self.send_json(install_codex())
            if path == "/api/codex/login":
                body = self.body_json()
                auth_trace("web_login_api_called", client=self.client_address[0], save_login=bool(body.get("save_login", True)),
                           user_agent=self.headers.get("User-Agent", "")[:300], origin=self.headers.get("Origin", ""),
                           referer=self.headers.get("Referer", ""))
                result = start_codex_login(bool(body.get("save_login", True)))
                auth_trace("web_login_api_result", result=result)
                return self.send_json(result)
            if path == "/api/codex/logout":
                return self.send_json(codex_logout())
            if path == "/api/projects/open-gfai":
                body = self.body_json()
                pid, p, cfg = open_gfai_file(body.get("path", ""))
                return self.send_json({"id": pid, "project_root": str(p), "config": cfg})
            if path == "/api/projects/create":
                body = self.body_json()
                return self.send_json(create_project(body.get("name", "Game Project"), body.get("goal", ""), body.get("research_mode", "deep")))
            m = re.match(r"^/api/project/([^/]+)/(.+)$", path)
            if not m:
                return self.send_json({"error":"unknown endpoint"}, 404)
            pid, action = m.group(1), m.group(2)
            p = project_path(pid); cfg = project_config(pid)
            if action == "config":
                body = self.body_json()
                allowed = {"research_mode","internet_research","commands","command_timeout_sec","iteration_pipeline","agent","visual","log_globs"}
                for k,v in body.items():
                    if k in allowed: cfg[k] = v
                write_json(p / "gameforge.json", cfg)
                return self.send_json(cfg)
            if action == "experiment/create":
                result = create_experimental_copy(pid)
                return self.send_json(result, 200 if result.get("ok") else int(result.get("status", 409)))
            if action == "experiment/promote":
                body = self.body_json()
                result = promote_experimental_copy(pid, bool(body.get("confirm")))
                return self.send_json(result, 200 if result.get("ok") else int(result.get("status", 409)))
            if action == "agent/start":
                return self.send_json(start_agent(pid))
            if action == "agent/pause":
                s = AGENTS.get(pid)
                if s: s.pause_event.set(); s.status="paused"; s.message="Paused by user"
                return self.send_json(agent_public(s) if s else {"status":"idle"})
            if action == "agent/resume":
                s = AGENTS.get(pid)
                if s and s.thread and s.thread.is_alive(): s.pause_event.clear(); s.status="running"; s.message="Resumed"
                else: return self.send_json(start_agent(pid))
                return self.send_json(agent_public(s))
            if action == "agent/stop":
                s = AGENTS.get(pid)
                if s:
                    stop_agent_now(s)
                    # Give the loop a brief chance to observe cancellation so the
                    # response normally returns "stopped" rather than lingering at
                    # "Stop requested" for an entire Codex/test timeout.
                    if s.thread and s.thread.is_alive():
                        s.thread.join(timeout=2.5)
                    if not s.thread or not s.thread.is_alive():
                        s.status = "stopped"
                        s.message = "Stopped by user; project state preserved."
                        set_agent_activity(s, "Stopped", s.message, "stopped")
                return self.send_json(agent_public(s) if s else {"status":"idle"})
            if action == "cv/start":
                return self.send_json(start_cv(pid))
            if action == "cv/stop":
                s = CVS.get(pid)
                if s: s.stop_event.set(); s.message="Stop requested"
                return self.send_json({"status": s.status if s else "idle", "message": s.message if s else ""})
            if action == "uploads/scan":
                return self.send_json(scan_uploads(pid))
            if action == "upload":
                q = urllib.parse.parse_qs(parsed.query)
                category = slugify((q.get("category") or ["REFERENCE"])[0]).upper()
                rel = (q.get("path") or [self.headers.get("X-Filename", "upload.bin")])[0]
                req = load_user_input_request(p)
                if (q.get("request_id") or [None])[0] and req:
                    validate_requested_upload(req, rel)
                    category = slugify(req.get("upload_category") or category).upper()
                rel = rel.replace("\\", "/").lstrip("/")
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length > 2_000_000_000:
                    return self.send_json({"error":"file too large"}, 413)
                dest_root = p / "UPLOAD" / category
                dest_root.mkdir(parents=True, exist_ok=True)
                dest = safe_child(dest_root, rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("wb") as f:
                    remaining = length
                    while remaining:
                        chunk = self.rfile.read(min(1024*1024, remaining))
                        if not chunk: break
                        f.write(chunk); remaining -= len(chunk)
                return self.send_json({"ok": True, "path": str(dest.relative_to(p)).replace("\\","/")})
            if action == "input-request/respond":
                body = self.body_json()
                req = load_user_input_request(p)
                if not req:
                    return self.send_json({"error": "no pending input request"}, 409)
                kind = req.get("kind", "text")
                if kind in {"text","url","choice","confirm"}:
                    response = body.get("value")
                    if kind == "url" and response and not re.match(r"^https?://", str(response), re.I):
                        return self.send_json({"error": "A valid http(s) URL is required"}, 400)
                    if kind == "choice" and response not in req.get("choices", []):
                        return self.send_json({"error": "Invalid choice"}, 400)
                    write_json(p / ".gameforge" / "user_input_response.json",
                               {"request_id": req.get("id"), "kind": kind, "value": response, "received_at": now_iso()})
                req["status"] = "fulfilled"
                req["fulfilled_at"] = now_iso()
                write_json(user_input_request_path(p), req)
                st = AGENTS.get(pid)
                if st and st.status == "waiting_for_user":
                    st.status = "paused"; st.message = "User input received; ready to resume"
                return self.send_json({"ok": True, "resume_after_submit": bool(req.get("resume_after_submit", True))})
            if action == "review/feedback":
                body = self.body_json()
                text_value = str(body.get("text", "") or "").strip()
                if not text_value:
                    return self.send_json({"error": "Feedback cannot be empty"}, 400)
                category = str(body.get("category", "general") or "general")[:80]
                review = append_user_feedback(p, text_value, category)
                # New feedback means there is new work to do even if the user previously
                # considered the project done.
                if review.get("user_done"):
                    review["user_done"] = False
                    review["reopened_at"] = now_iso()
                    save_user_review(p, review)
                st = AGENTS.get(pid)
                if st and st.status == "user-complete":
                    st.status = "paused"
                    st.message = "New user feedback received; ready to continue from the current state"
                return self.send_json(load_user_review(p))
            if action == "review/satisfaction":
                body = self.body_json()
                raw = body.get("value")
                value = None if raw in (None, "") else int(raw)
                if value is not None and not 1 <= value <= 5:
                    return self.send_json({"error": "Satisfaction must be from 1 to 5"}, 400)
                review = load_user_review(p)
                review["satisfaction"] = value
                review["satisfaction_updated_at"] = now_iso()
                return self.send_json(save_user_review(p, review))
            if action == "review/done":
                body = self.body_json()
                done = bool(body.get("done", True))
                review = load_user_review(p)
                review["user_done"] = done
                if done:
                    review["marked_done_at"] = now_iso()
                    review["done_iteration"] = AGENTS.get(pid).iteration if AGENTS.get(pid) else None
                    checkpoint = git_checkpoint(p, "GameForge user-marked done checkpoint")
                    review["done_checkpoint"] = checkpoint.get("rev", "")
                    st = AGENTS.get(pid)
                    if st:
                        st.pause_event.set()
                        st.status = "user-complete"
                        st.message = "User marked this result done"
                else:
                    review["reopened_at"] = now_iso()
                    st = AGENTS.get(pid)
                    if st:
                        st.pause_event.clear()
                        if st.thread and st.thread.is_alive():
                            st.status = "running"
                            st.message = "User reopened the project; continuing from the saved state"
                    # If the previous agent thread already exited because it was user-complete,
                    # start a fresh loop against the same files/Git history.
                    if not st or not st.thread or not st.thread.is_alive():
                        start_agent(pid)
                return self.send_json(save_user_review(p, review))
            if action in {"run/build","run/test","run/launch"}:
                which = action.split("/")[1]
                cmd = cfg.get("commands", {}).get(which, "")
                result = run_shell(cmd, p, int(cfg.get("command_timeout_sec",1800)), p / f"logs/manual-{which}-{int(time.time())}.log")
                return self.send_json(result)
            if action == "git/checkpoint":
                body = self.body_json()
                return self.send_json(git_checkpoint(p, body.get("message", "GameForge manual checkpoint")))
            if action == "git/status":
                return self.send_json(git_status(p))
            if action == "git/rollback":
                body = self.body_json()
                return self.send_json(git_rollback(p, body.get("revision", "")))
            if action == "process/start":
                body = self.body_json()
                return self.send_json(start_managed_process(pid, body.get("command")))
            if action == "process/stop":
                return self.send_json(stop_managed_process(pid))
            if action == "input/replay":
                body = self.body_json()
                return self.send_json(run_input_sequence(pid, body.get("sequence", [])))
            if action == "research/run":
                body = self.body_json()
                return self.send_json(run_research_task(pid, body.get("question", "Research anything currently blocking professional-quality completion of the user's game-development goal.")))
            if action == "assets/analyze":
                return self.send_json(analyze_assets(pid))
            if action == "acceptance/update":
                body = self.body_json()
                acc = read_json(p / ".gameforge/acceptance.json", {}) or {}
                if "criteria" in body and isinstance(body["criteria"], list): acc["criteria"] = body["criteria"]
                if "project_complete" in body: acc["project_complete"] = bool(body["project_complete"])
                acc["updated_at"] = now_iso()
                write_json(p / ".gameforge/acceptance.json", acc)
                return self.send_json(acc)
            return self.send_json({"error":"unknown action"}, 404)
        except FileNotFoundError:
            return self.send_json({"error":"project not found"}, 404)
        except Exception as exc:
            return self.send_json({"error": str(exc), "trace": traceback.format_exc()[-3000:]}, 500)


def main() -> None:
    global APP_SERVER
    parser = argparse.ArgumentParser(description="GameForge AI local game-development studio")
    parser.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 for LAN access")
    parser.add_argument("--port", type=int, default=4217)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--project-file", help="Open/register a .gfai project entry point")
    args = parser.parse_args()
    selected_project = None
    if args.project_file:
        selected_project, _, _ = open_gfai_file(args.project_file)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    APP_SERVER = server
    refresh_windows_environment()
    ensure_codex_async()
    url = f"http://127.0.0.1:{args.port}"
    if selected_project:
        url += f"/?project={urllib.parse.quote(selected_project)}"
    print(f"GameForge AI Single-File running at {url}")
    if args.host == "0.0.0.0":
        print("LAN mode enabled. Only use on a trusted network; the control API can modify project files and run configured commands.")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping GameForge AI")
    finally:
        graceful_session_shutdown("server-exit")
        server.server_close()
        APP_SERVER = None

if __name__ == "__main__":
    main()
