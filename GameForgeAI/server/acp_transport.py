"""ACP v1 client transport for externally installed coding agents.

Supports session/new, session/prompt, session/update, session/cancel and
session/request_permission. Steering is deliberately unavailable unless an
agent advertises a safe extension; queued instructions remain durable.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .codex_app_server import CodexAppServer, AppServerUnavailable, AppServerProtocolError
from .fusion_mcp import acp_mcp_servers


class AcpAgentTransport(CodexAppServer):
    def __init__(self, command: list[str], *, cwd: Path, env: dict[str, str],
                 mcp_servers: list[dict[str, Any]] | None = None,
                 on_event=None, on_question=None) -> None:
        if not command or not all(isinstance(v, str) and v for v in command):
            raise ValueError("ACP executable and arguments are required")
        super().__init__(command, shell=False, cwd=cwd, env=env,
                         on_event=on_event, on_question=on_question)
        self.mcp_servers = mcp_servers or []
        self.session_id: str | None = None
        self._turn_active = False
        self._capabilities: dict[str, Any] = {}

    @property
    def active(self) -> bool:
        return bool(self._turn_active and self.session_id and self.process and self.process.poll() is None)

    def open(self) -> None:
        if self.process and self.process.poll() is None and self.session_id:
            return
        self._closed.clear()
        self._stderr_lines.clear()
        kwargs: dict[str, Any] = {
            "cwd": str(self.cwd), "env": self.env, "shell": False,
            "stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE, "text": True, "encoding": "utf-8",
            "errors": "replace", "bufsize": 1,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        try:
            self.process = subprocess.Popen(self.command, **kwargs)
        except (OSError, ValueError) as exc:
            raise AppServerUnavailable(f"ACP launch failed: {exc}") from exc
        self._stdout_thread = threading.Thread(target=self._reader, daemon=True, name="gameforge-acp-rpc")
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True, name="gameforge-acp-stderr")
        self._stdout_thread.start()
        self._stderr_thread.start()
        try:
            hello = self._request("initialize", {
                "protocolVersion": 1,
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False},
                                       "terminal": False},
                "clientInfo": {"name": "gameforge_ai", "title": "GameForge AI", "version": "1"},
            }, timeout=15)
            self._capabilities = hello.get("agentCapabilities") or {}
            mcp = acp_mcp_servers(self.mcp_servers, self.env)
            started = self._request("session/new", {"cwd": str(self.cwd), "mcpServers": mcp}, timeout=20)
            session_id = started.get("sessionId")
            if not isinstance(session_id, str) or not session_id:
                raise AppServerProtocolError("ACP session/new returned no sessionId")
            self.session_id = session_id
        except Exception as exc:
            self.close()
            raise AppServerUnavailable(f"ACP handshake failed: {exc}") from exc

    def steer(self, text: str) -> bool:
        # ACP v1 does not guarantee concurrent session/prompt support.
        return False

    def interrupt(self) -> bool:
        if not self.active:
            return False
        self._send({"method": "session/cancel", "params": {"sessionId": self.session_id}})
        return True

    def run_turn(self, prompt: str, *, timeout: float, trace_path: Path,
                 stop_event: threading.Event, interrupt_event: threading.Event) -> subprocess.CompletedProcess[str]:
        self.open()
        if not self.session_id:
            raise AppServerProtocolError("ACP session not initialized")
        prompt = prompt.encode("utf-8", errors="replace").decode("utf-8")
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        result: dict[str, Any] = {}
        complete = threading.Event()
        self._turn_active = True

        def wait_prompt() -> None:
            try:
                result["value"] = self._request("session/prompt", {
                    "sessionId": self.session_id,
                    "prompt": [{"type": "text", "text": prompt}],
                }, timeout=timeout + 10)
            except Exception as exc:
                result["error"] = str(exc)
            finally:
                complete.set()

        worker = threading.Thread(target=wait_prompt, daemon=True, name="gameforge-acp-prompt")
        worker.start()
        cancelled = False
        limit = time.monotonic() + timeout
        try:
            with trace_path.open("a", encoding="utf-8", errors="replace", buffering=1) as trace:
                while not complete.is_set():
                    if (stop_event.is_set() or interrupt_event.is_set()) and not cancelled:
                        cancelled = True
                        try:
                            self.interrupt()
                        except AppServerProtocolError:
                            pass
                        limit = min(limit, time.monotonic() + 4)
                    if self._closed.is_set():
                        raise AppServerProtocolError("ACP agent connection closed")
                    if time.monotonic() > limit:
                        self.close()
                        if cancelled:
                            return subprocess.CompletedProcess(self.command, 130, "", "ACP turn interrupted")
                        raise subprocess.TimeoutExpired(self.command, timeout)
                    try:
                        msg = self._notifications.get(timeout=0.15)
                    except queue.Empty:
                        continue
                    trace.write(json.dumps(msg, ensure_ascii=True) + "\n")
                # Drain remaining streamed notifications for reproducible diagnostics.
                while True:
                    try:
                        msg = self._notifications.get_nowait()
                    except queue.Empty:
                        break
                    trace.write(json.dumps(msg, ensure_ascii=True) + "\n")
            if "error" in result:
                raise AppServerProtocolError(f"ACP session/prompt: {result['error']}")
            reason = str((result.get("value") or {}).get("stopReason") or "")
            failure = reason in {"refusal", "error", "cancelled"}
            code = 130 if cancelled or reason == "cancelled" else (1 if failure else 0)
            return subprocess.CompletedProcess(self.command, code, "", reason if failure else "")
        finally:
            self._turn_active = False

    def close(self) -> None:
        self.session_id = None
        self._turn_active = False
        super().close()
