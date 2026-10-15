"""Offline protocol tests with a fake Codex app-server (no account required)."""
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.codex_app_server import CodexAppServer, AppServerUnavailable

FAKE_SERVER = r"""
import json, sys, threading
lock = threading.Lock()
pending = {}
def send(value):
    with lock:
        print(json.dumps(value), flush=True)
def emit(turn, status):
    with lock:
        if turn not in pending:
            return
        pending.pop(turn)
        print(json.dumps({"method":"turn/completed","params":{"threadId":"test-thread",
             "turn":{"id":turn,"status":status}}}), flush=True)
for line in sys.stdin:
    obj = json.loads(line)
    method = obj.get("method")
    rid = obj.get("id")
    if method == "initialize":
        send({"id":rid,"result":{"userAgent":"test"}})
    elif method == "thread/start" or method == "thread/resume":
        send({"id":rid,"result":{"thread":{"id":"test-thread"}}})
    elif method == "turn/start":
        turn = "turn-" + str(rid)
        pending[turn] = True
        send({"id":rid,"result":{"turn":{"id":turn,"status":"inProgress"}}})
        timer = threading.Timer(0.8, emit, args=(turn, "completed"))
        timer.daemon = True
        timer.start()
    elif method == "turn/steer":
        send({"id":rid,"result":{"turnId":obj["params"]["expectedTurnId"]}})
    elif method == "turn/interrupt":
        send({"id":rid,"result":{}})
        emit(obj["params"]["turnId"], "interrupted")
    elif method == "initialized":
        pass
"""


class AppServerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.client = CodexAppServer(
            [sys.executable, "-u", "-c", FAKE_SERVER], shell=False,
            cwd=self.path, env=os.environ.copy(),
        )

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_handshake_and_persisted_thread(self):
        self.client.open()
        self.assertEqual(self.client.thread_id, "test-thread")
        self.assertTrue((self.path / ".gameforge" / "codex-app-thread.json").exists())
        self.assertFalse(self.client.active)

    def test_live_steering_and_completion(self):
        done = []
        def run():
            done.append(self.client.run_turn("Build game", timeout=5,
                trace_path=self.path / "trace.jsonl",
                stop_event=threading.Event(), interrupt_event=threading.Event()))
        task = threading.Thread(target=run)
        task.start()
        for _ in range(100):
            if self.client.active:
                break
            time.sleep(.02)
        self.assertTrue(self.client.active)
        self.assertTrue(self.client.steer("Fix tests first"))
        task.join(7)
        self.assertFalse(task.is_alive())
        self.assertEqual(done[0].returncode, 0)
        self.assertTrue(self.client.process and self.client.process.poll() is None)
        self.assertTrue((self.path / "trace.jsonl").exists())

    def test_interrupt_without_replaying_turn(self):
        interrupt = threading.Event()
        results = []
        task = threading.Thread(target=lambda: results.append(
            self.client.run_turn("Very long task", timeout=5,
                trace_path=self.path / "interrupt.jsonl",
                stop_event=threading.Event(), interrupt_event=interrupt)))
        task.start()
        for _ in range(100):
            if self.client.active:
                break
            time.sleep(.02)
        self.assertTrue(self.client.active)
        interrupt.set()
        task.join(7)
        self.assertFalse(task.is_alive())
        self.assertEqual(results[0].returncode, 130)
        self.assertFalse(self.client.active)

    def test_persistent_turn_reuse(self):
        stop = threading.Event()
        interrupt = threading.Event()
        first = self.client.run_turn("First iteration", timeout=5,
            trace_path=self.path / "one.jsonl", stop_event=stop, interrupt_event=interrupt)
        self.assertEqual(first.returncode, 0)
        pid = self.client.process.pid
        second = self.client.run_turn("Second iteration", timeout=5,
            trace_path=self.path / "two.jsonl", stop_event=stop, interrupt_event=interrupt)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(self.client.process.pid, pid)
        self.assertEqual(self.client.thread_id, "test-thread")

    def test_gameforge_agent_wrapper_uses_persistent_transport(self):
        from unittest.mock import patch
        from server import app
        state = app.AgentState(project_id="test-fixture")
        try:
            with patch.object(app, "_command_invocation", return_value=(
                [sys.executable, "-u", "-c", FAKE_SERVER], False
            )), patch.object(app, "_codex_process_env", return_value=os.environ.copy()):
                result = app.run_codex_fusion_stream(
                    ["exec", "--json", "-"], cwd=self.path,
                    input_text="GameForge integration test",
                    timeout=5, trace_path=self.path / "gameforge.jsonl",
                    state=state, permission_mode="full-auto",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIsNotNone(state.transport)
                self.assertEqual(state.transport.thread_id, "test-thread")
                self.assertEqual(state.active_process_kind, "codex-app-server")
        finally:
            if state.transport:
                state.transport.close()

    def test_unavailable_fails_closed(self):
        self.client.close()
        broken = CodexAppServer(
            [str(self.path / "missing-codex")], shell=False,
            cwd=self.path, env=os.environ.copy())
        with self.assertRaises(AppServerUnavailable):
            broken.open()


if __name__ == "__main__":
    unittest.main()
