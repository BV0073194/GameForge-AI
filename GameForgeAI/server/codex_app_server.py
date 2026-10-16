"""Persistent Codex app-server transport for GameForge Fusion.

No external dependencies. Uses the installed Codex CLI's newline-delimited
JSON-RPC interface and retains an existing thread across verified turns.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable


class AppServerUnavailable(RuntimeError):
    """The persistent transport could not start before agent work began."""


class AppServerProtocolError(RuntimeError):
    """Codex returned a protocol or turn failure."""


class CodexAppServer:
    def __init__(
        self,
        command: str | list[str],
        *,
        shell: bool,
        cwd: Path,
        env: dict[str, str],
        permission_mode: str = "full-auto",
        on_event: Callable[[dict[str, Any]], None] | None = None,
        on_question: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        self.command, self.shell, self.cwd, self.env = command, shell, cwd, env
        self.permission_mode = permission_mode
        self.on_event, self.on_question = on_event, on_question
        self.process: subprocess.Popen[str] | None = None
        self.thread_id: str | None = None
        self.turn_id: str | None = None
        self.turn_active = False
        self._write_lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._pending: dict[int, tuple[threading.Event, dict[str, Any]]] = {}
        self._next_id = 1
        self._notifications: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=4096)
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_lines: list[str] = []
        self._closed = threading.Event()
        self._thread_file = cwd / ".gameforge" / "codex-app-thread.json"

    @property
    def active(self) -> bool:
        return bool(self.process and self.process.poll() is None and self.turn_active and self.turn_id)

    def _send(self, msg: dict[str, Any]) -> None:
        with self._write_lock:
            if self.process is None or self.process.poll() is not None or self.process.stdin is None:
                raise AppServerProtocolError("Codex app-server is not running")
            self.process.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def _request(self, method: str, params: dict[str, Any], timeout: float = 15) -> Any:
        with self._request_lock:
            request_id = self._next_id
            self._next_id += 1
            done = threading.Event()
            box: dict[str, Any] = {}
            self._pending[request_id] = (done, box)
        try:
            self._send({"id": request_id, "method": method, "params": params})
            if not done.wait(timeout):
                raise AppServerProtocolError(f"{method}: no response within {timeout:g}s")
            if "error" in box:
                raise AppServerProtocolError(f"{method}: {str(box['error'])[:900]}")
            return box.get("result") or {}
        finally:
            with self._request_lock:
                self._pending.pop(request_id, None)

    def _reader(self) -> None:
        try:
            assert self.process is not None and self.process.stdout is not None
            for line in self.process.stdout:
                if len(line) > 2_000_000:
                    continue
                try:
                    msg = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(msg, dict):
                    continue
                if "id" in msg and "method" not in msg:
                    with self._request_lock:
                        waiter = self._pending.get(msg["id"])
                    if waiter:
                        waiter[1].update(msg)
                        waiter[0].set()
                    continue
                if "id" in msg and "method" in msg:
                    accepted = False
                    if self.on_question is not None:
                        try:
                            accepted = bool(self.on_question(msg))
                        except Exception:
                            accepted = False
                    if not accepted:
                        # Never silently approve an unknown privileged request.
                        try:
                            self._send({"id": msg["id"], "error": {"code": -32601, "message": "Unsupported client request"}})
                        except Exception:
                            pass
                    continue
                if self.on_event:
                    try:
                        self.on_event(msg)
                    except Exception:
                        pass
                try:
                    self._notifications.put_nowait(msg)
                except queue.Full:
                    # Preserve control events even under high-volume delta output.
                    if msg.get("method") == "turn/completed":
                        try:
                            self._notifications.get_nowait()
                            self._notifications.put_nowait(msg)
                        except queue.Empty:
                            pass
        finally:
            self._closed.set()
            with self._request_lock:
                for done, box in self._pending.values():
                    box["error"] = "Codex app-server connection closed"
                    done.set()

    def _read_stderr(self) -> None:
        if self.process is None or self.process.stderr is None:
            return
        for line in self.process.stderr:
            self._stderr_lines.append(line[-4000:])
            if len(self._stderr_lines) > 150:
                del self._stderr_lines[:50]

    def open(self) -> None:
        if self.process and self.process.poll() is None:
            return
        self._closed.clear()
        self._stderr_lines.clear()
        kwargs: dict[str, Any] = {
            "cwd": str(self.cwd), "shell": self.shell, "env": self.env,
            "stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE, "text": True, "encoding": "utf-8", "errors": "replace",
            "bufsize": 1,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        try:
            self.process = subprocess.Popen(self.command, **kwargs)
        except (OSError, ValueError) as exc:
            raise AppServerUnavailable(str(exc)) from exc
        self._stdout_thread = threading.Thread(target=self._reader, daemon=True, name="gameforge-codex-rpc")
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True, name="gameforge-codex-errors")
        self._stdout_thread.start()
        self._stderr_thread.start()
        try:
            self._request("initialize", {"clientInfo": {
                "name": "gameforge_ai", "title": "GameForge AI", "version": "1.0.4"
            }, "capabilities": {"experimentalApi": True}}, timeout=12)
            self._send({"method": "initialized", "params": {}})
            saved: dict[str, Any] = {}
            try:
                saved = json.loads(self._thread_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            previous = saved.get("thread_id") if saved.get("cwd") == str(self.cwd.resolve()) else None
            if isinstance(previous, str) and previous:
                try:
                    result = self._request("thread/resume", {"threadId": previous}, timeout=12)
                    self.thread_id = (result.get("thread") or {}).get("id") or previous
                except AppServerProtocolError:
                    self.thread_id = None
            if not self.thread_id:
                params: dict[str, Any] = {"cwd": str(self.cwd)}
                if self.permission_mode == "full-auto":
                    params.update({"approvalPolicy": "never", "sandbox": "danger-full-access"})
                else:
                    params["sandbox"] = "workspace-write"
                result = self._request("thread/start", params, timeout=12)
                self.thread_id = (result.get("thread") or {}).get("id")
            if not self.thread_id:
                raise AppServerProtocolError("thread/start returned no thread ID")
            self._thread_file.parent.mkdir(parents=True, exist_ok=True)
            self._thread_file.write_text(json.dumps({
                "thread_id": self.thread_id, "cwd": str(self.cwd.resolve()),
            }), encoding="utf-8")
        except Exception as exc:
            self.close()
            raise AppServerUnavailable(str(exc)) from exc

    def steer(self, text: str) -> bool:
        if not self.active or not text.strip():
            return False
        self._request("turn/steer", {
            "threadId": self.thread_id,
            "expectedTurnId": self.turn_id,
            "input": [{"type": "text", "text": text.strip()}],
        }, timeout=8)
        return True

    def interrupt(self) -> bool:
        if not self.active:
            return False
        self._request("turn/interrupt", {
            "threadId": self.thread_id, "turnId": self.turn_id,
        }, timeout=6)
        return True

    def reply(self, request_id: int | str, result: dict[str, Any]) -> None:
        self._send({"id": request_id, "result": result})

    def run_turn(
        self,
        prompt: str,
        *,
        timeout: float,
        trace_path: Path,
        stop_event: threading.Event,
        interrupt_event: threading.Event,
    ) -> subprocess.CompletedProcess[str]:
        self.open()
        assert self.thread_id
        prompt = prompt.encode("utf-8", errors="replace").decode("utf-8")
        response = self._request("turn/start", {
            "threadId": self.thread_id, "input": [{"type": "text", "text": prompt}],
        }, timeout=20)
        turn = response.get("turn") or {}
        turn_id = turn.get("id")
        if not turn_id:
            raise AppServerProtocolError("turn/start did not return a turn ID")
        self.turn_id = str(turn_id)
        self.turn_active = True
        ended: dict[str, Any] | None = None
        interrupted = False
        deadline = time.monotonic() + timeout
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with trace_path.open("a", encoding="utf-8", buffering=1) as trace:
                while time.monotonic() < deadline:
                    if stop_event.is_set() or interrupt_event.is_set():
                        interrupted = True
                        try:
                            self.interrupt()
                        except AppServerProtocolError:
                            pass
                        # Acknowledgement is not completion; wait briefly for the event.
                        deadline = min(deadline, time.monotonic() + 4)
                        # Avoid sending interrupt repeatedly.
                        break
                    if self._closed.is_set():
                        raise AppServerProtocolError("Codex app-server closed during turn")
                    try:
                        msg = self._notifications.get(timeout=0.15)
                    except queue.Empty:
                        continue
                    trace.write(json.dumps(msg, ensure_ascii=False) + "\n")
                    if msg.get("method") != "turn/completed":
                        continue
                    params = msg.get("params") or {}
                    if params.get("threadId") != self.thread_id:
                        continue
                    finished = params.get("turn") or {}
                    if finished.get("id") == self.turn_id:
                        ended = finished
                        break
                if interrupted and ended is None:
                    while time.monotonic() < deadline:
                        try:
                            msg = self._notifications.get(timeout=0.15)
                        except queue.Empty:
                            continue
                        trace.write(json.dumps(msg, ensure_ascii=False) + "\n")
                        if msg.get("method") == "turn/completed":
                            params = msg.get("params") or {}
                            if params.get("threadId") == self.thread_id and (params.get("turn") or {}).get("id") == self.turn_id:
                                ended = params["turn"]
                                break
            if ended is None:
                if interrupted:
                    self.close()
                    return subprocess.CompletedProcess(self.command, 130, "", "Interrupted by user")
                self.close()
                raise subprocess.TimeoutExpired(self.command, timeout)
            status = ended.get("status", "failed")
            error = ended.get("error") or ""
            code = 0 if status == "completed" and not interrupted else (130 if interrupted or status == "interrupted" else 1)
            return subprocess.CompletedProcess(self.command, code, "", str(error) if error else "")
        finally:
            self.turn_active = False
            self.turn_id = None

    def close(self) -> None:
        proc = self.process
        self.process = None
        self.turn_active = False
        self.turn_id = None
        if proc and proc.poll() is None:
            # App-server is a process-group leader; terminate descendants too.
            # In particular, Windows npm .cmd wrappers can outlive their shell.
            if os.name == "nt":
                try:
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=8, check=False)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            else:
                import signal
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    import signal
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except (OSError, ProcessLookupError):
                        pass
                try:
                    proc.kill()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        self._closed.set()
