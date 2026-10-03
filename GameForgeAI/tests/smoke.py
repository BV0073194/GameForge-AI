from __future__ import annotations
import json, os, tempfile, threading, time, urllib.request, sys, zipfile
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

    # Stop must interrupt an active long-running project command promptly instead
    # of merely setting a flag that is observed after the command exits.
    stop_state = app.AgentState(project_id=cfg["id"])
    def request_stop_when_active():
        deadline = time.time() + 5
        while time.time() < deadline and stop_state.active_process is None:
            time.sleep(0.05)
        app.stop_agent_now(stop_state)
    stopper = threading.Thread(target=request_stop_when_active, daemon=True)
    stopper.start()
    stop_started = time.time()
    stopped = app.run_shell(
        f'"{sys.executable}" -c "import time; time.sleep(30)"',
        p,
        timeout=60,
        activity_state=stop_state,
    )
    stopper.join(timeout=2)
    assert stopped.get("cancelled") is True, stopped
    assert time.time() - stop_started < 8, stopped

    mf = next(p.glob("*.gfai"))
    pid, rp, cfg2 = app.open_gfai_file(mf)
    assert pid == cfg["id"]
    assert rp == p.resolve()
    idx = app.scan_project_tree(p)
    assert idx["file_count"] > 0

    # The strict fast pipeline is now production behavior on main. Targeted
    # diagnostics may accelerate iteration, but they cannot close feedback or
    # completion without the configured full build/test quality gate.
    production_cfg = app.project_config(cfg["id"])
    pipeline = app.iteration_pipeline_settings(production_cfg)
    assert pipeline["quality_mode"] == "strict-original"
    assert pipeline["full_configured_test_required"] is True
    assert pipeline["allow_savestate_for_trusted_evidence"] is False

    before_review = app.append_user_feedback(p, "Strict quality smoke feedback.", "general")
    candidate = app.load_user_review(p)
    candidate["feedback"][-1]["ready_for_verification"] = True
    candidate["feedback"][-1]["resolution"] = "Implemented in smoke fixture."
    candidate["feedback"][-1]["evidence"] = "Targeted diagnostic passed."
    app.save_user_review(p, candidate)

    after_targeted_only = app.reconcile_feedback_work_orders(
        p,
        before_review,
        {"configured": False, "ok": True},
        {"configured": False, "ok": True},
        verification_complete=True,
    )
    assert after_targeted_only["feedback"][-1]["addressed"] is False
    assert after_targeted_only["feedback"][-1]["ready_for_verification"] is True

    after_full_gate = app.reconcile_feedback_work_orders(
        p,
        before_review,
        {"configured": True, "ok": True},
        {"configured": True, "ok": True},
        verification_complete=True,
    )
    assert after_full_gate["feedback"][-1]["addressed"] is True
    assert after_full_gate["feedback"][-1]["verification_class"] == "targeted-plus-original-full-regression"

    # Clean & Build must run a real clean step first and only then build.
    clean_script = p / "smoke_clean.py"
    build_script = p / "smoke_build.py"
    clean_script.write_text("from pathlib import Path\nPath('clean.marker').write_text('clean', encoding='utf-8')\n", encoding="utf-8")
    build_script.write_text(
        "from pathlib import Path\n"
        "assert Path('clean.marker').exists()\n"
        "Path('build.marker').write_text('build', encoding='utf-8')\n",
        encoding="utf-8",
    )
    cfg3 = app.project_config(cfg["id"])
    cfg3["commands"]["clean"] = f'"{sys.executable}" smoke_clean.py'
    cfg3["commands"]["build"] = f'"{sys.executable}" smoke_build.py'
    cfg3["cleanup"].update({"log_keep_files": 10, "capture_keep_groups": 2, "research_keep_iterations": 3})
    app.write_json(p / "gameforge.json", cfg3)
    clean_build = app.run_clean_build(cfg["id"])
    assert clean_build["ok"], clean_build
    assert (p / "clean.marker").exists()
    assert (p / "build.marker").exists()

    # Automatic cleanup archives old logs before deletion, prunes only old
    # iteration-specific research/capture groups, and honors explicit AI-safe
    # workspace candidates.
    logs = p / "logs"
    logs.mkdir(exist_ok=True)
    for i in range(20):
        q = logs / f"old-{i:02d}.log"
        q.write_text(f"log {i}", encoding="utf-8")
        os.utime(q, (1000 + i, 1000 + i))
    research = p / "research"
    research.mkdir(exist_ok=True)
    for i in range(1, 9):
        (research / f"ITERATION{i}_EVIDENCE.json").write_text("{}", encoding="utf-8")
    captures = p / "captures"
    captures.mkdir(exist_ok=True)
    for i in range(1, 6):
        d = captures / f"iteration-{i:02d}"
        d.mkdir(exist_ok=True)
        (d / "frame.png").write_bytes(b"not-an-image-needed-for-cleanup-smoke")
        os.utime(d, (1000 + i, 1000 + i))
    disposable = p / "workspace" / "tools" / "disposable-smoke.py"
    disposable.parent.mkdir(parents=True, exist_ok=True)
    disposable.write_text("print('obsolete')", encoding="utf-8")
    app.write_json(p / ".gameforge" / "cleanup_candidates.json", {
        "candidates": [{"path": "workspace/tools/disposable-smoke.py", "safe_to_delete": True, "reason": "smoke fixture"}]
    })
    cleanup = app.cleanup_project_artifacts(p, app.project_config(cfg["id"]), reason="smoke")
    assert cleanup["archived_logs"] >= 10, cleanup
    assert (logs / "old_logs.zip").exists()
    with zipfile.ZipFile(logs / "old_logs.zip", "r") as zf:
        assert zf.namelist()
        assert zf.testzip() is None
    assert not disposable.exists()
    remaining_research = list(research.glob("ITERATION*_EVIDENCE.json"))
    assert len(remaining_research) <= 3, [x.name for x in remaining_research]
    remaining_capture_dirs = [x for x in captures.iterdir() if x.is_dir()]
    assert len(remaining_capture_dirs) <= 2, [x.name for x in remaining_capture_dirs]

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
