"""Offline regression for project MCP configuration and ACP agent transport."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.fusion_mcp import validate_mcp_servers, codex_mcp_config, acp_mcp_servers, public_mcp_servers
from server.acp_transport import AcpAgentTransport

FAKE_ACP = r"""
import json, sys, threading
lock = threading.RLock()
turn = None
pending = None
def emit(obj):
    with lock: print(json.dumps(obj), flush=True)
def finish():
    global pending
    if pending:
        emit({"id": pending, "result": {"stopReason": "end_turn"}})
        pending = None
for line in sys.stdin:
    msg = json.loads(line)
    method, rid = msg.get("method"), msg.get("id")
    if method == "initialize":
        emit({"id":rid,"result":{"protocolVersion":1,"agentCapabilities":{}}})
    elif method == "session/new":
        assert msg["params"]["cwd"]
        emit({"id":rid,"result":{"sessionId":"mock-session"}})
    elif method == "session/prompt":
        pending = rid
        emit({"method":"session/update","params":{"sessionId":"mock-session",
             "update":{"sessionUpdate":"tool_call","toolCallId":"edit-1","title":"Editing test"}}})
        if "QUESTION" in msg["params"]["prompt"][0]["text"]:
            emit({"id":"request-1","method":"session/request_permission",
                  "params":{"sessionId":"mock-session","toolCall":{"title":"Safe edit"},
                            "options":[{"optionId":"allow_once","name":"Allow once","kind":"allow_once"}]}})
        else:
            timer = threading.Timer(.25, finish)
            timer.daemon = True
            timer.start()
    elif method == "session/cancel":
        if pending:
            emit({"id":pending,"result":{"stopReason":"cancelled"}})
            pending = None
    elif rid == "request-1":
        finish()
"""


class FusionProtocolsTests(unittest.TestCase):
    def test_mcp_http_env_secrets_not_persisted(self):
        servers = validate_mcp_servers([{
            "name": "dev-tools", "type": "http", "url": "https://tools.example/mcp",
            "bearer_token_env_var": "MCP_SECRET",
            "env_http_headers": {"X-Account": "MCP_ACCOUNT"},
        }])
        self.assertNotIn("actual-token", json.dumps(public_mcp_servers(servers)))
        config = codex_mcp_config(servers)
        self.assertEqual(config["mcp_servers"]["dev-tools"]["bearer_token_env_var"], "MCP_SECRET")
        acp = acp_mcp_servers(servers, {"MCP_SECRET": "actual-token", "MCP_ACCOUNT": "my-account"})
        self.assertIn({"name": "Authorization", "value": "Bearer actual-token"}, acp[0]["headers"])
        self.assertIn({"name": "X-Account", "value": "my-account"}, acp[0]["headers"])
        self.assertNotIn("actual-token", json.dumps(servers))

    def test_mcp_stdio_and_invalid_values(self):
        values = validate_mcp_servers([{"name": "local", "type": "stdio",
                                        "command": "/usr/bin/tool", "args": ["--stdio"],
                                        "env_vars": ["HOME"]}])
        self.assertEqual(codex_mcp_config(values)["mcp_servers"]["local"]["args"], ["--stdio"])
        self.assertEqual(acp_mcp_servers(values, {"HOME": "/home/user"})[0]["env"],
                         [{"name": "HOME", "value": "/home/user"}])
        for invalid in [
            [{"name": "x", "type": "http", "url": "file:///etc/passwd"}],
            [{"name": "x", "type": "http", "url": "https://user:password@example.com/mcp"}],
            [{"name": "bad name", "type": "http", "url": "https://example.com"}],
            [{"name": "same", "type": "http", "url": "https://example.com"},
             {"name": "same", "type": "http", "url": "https://example.org"}],
        ]:
            with self.assertRaises(ValueError):
                validate_mcp_servers(invalid)

    def test_acp_stream_and_question_response(self):
        with tempfile.TemporaryDirectory() as td:
            events, requests = [], []
            transport = AcpAgentTransport([sys.executable, "-u", "-c", FAKE_ACP],
                cwd=Path(td), env=os.environ.copy(),
                on_event=lambda msg: events.append(msg),
                on_question=lambda msg: requests.append(msg) or (
                    transport.reply(msg["id"], {"outcome": {"outcome": "cancelled"}}) or True))
            try:
                response = transport.run_turn("QUESTION: choose",
                    timeout=5, trace_path=Path(td) / "acp.jsonl",
                    stop_event=threading.Event(), interrupt_event=threading.Event())
                self.assertEqual(response.returncode, 0, response.stderr)
                self.assertEqual(requests[0]["method"], "session/request_permission")
                self.assertTrue(any(x.get("method") == "session/update" for x in events))
                self.assertTrue((Path(td) / "acp.jsonl").read_text(encoding="utf-8").strip())
            finally:
                transport.close()

    def test_acp_interrupt_cancels_without_replaying(self):
        with tempfile.TemporaryDirectory() as td:
            interrupt = threading.Event()
            transport = AcpAgentTransport([sys.executable, "-u", "-c", FAKE_ACP],
                cwd=Path(td), env=os.environ.copy())
            result = []
            try:
                worker = threading.Thread(target=lambda: result.append(transport.run_turn(
                    "Work until stopped", timeout=5,
                    trace_path=Path(td) / "trace.jsonl",
                    stop_event=threading.Event(), interrupt_event=interrupt)))
                worker.start()
                for _ in range(100):
                    if transport.active:
                        break
                    time.sleep(.01)
                self.assertTrue(transport.active)
                interrupt.set()
                worker.join(timeout=6)
                self.assertFalse(worker.is_alive())
                self.assertEqual(result[0].returncode, 130)
            finally:
                transport.close()


if __name__ == "__main__":
    unittest.main()
