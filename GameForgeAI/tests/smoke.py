from __future__ import annotations
import json, tempfile, threading, time, urllib.request, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server import app

with tempfile.TemporaryDirectory() as td:
    app.USER_DATA = Path(td)
    app.PROJECTS = Path(td)/"projects"
    app.GLOBAL_UPLOAD = Path(td)/"UPLOAD"
    app.GLOBAL_LOGS = Path(td)/"logs"
    app.REGISTRY_FILE = Path(td)/"project_registry.json"
    for p in (app.PROJECTS, app.GLOBAL_UPLOAD, app.GLOBAL_LOGS):
        p.mkdir(parents=True, exist_ok=True)

    cfg = app.create_project("Smoke Project", "Make a playable test project.", "off")
    p = app.project_path(cfg["id"])
    mf = next(p.glob("*.gfai"))
    pid, rp, cfg2 = app.open_gfai_file(mf)
    assert pid == cfg["id"]
    assert rp == p.resolve()
    idx = app.scan_project_tree(p)
    assert idx["file_count"] > 0

    server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as r:
            data = json.loads(r.read())
            assert "python" in data
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            page = r.read().decode("utf-8", "replace")
            assert "GameForge" in page
    finally:
        server.shutdown()
print("SMOKE_OK")
