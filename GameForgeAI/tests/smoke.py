from __future__ import annotations
import json, os, tempfile, threading, time, urllib.request, sys
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

    experiment = app.create_experimental_copy(cfg["id"])
    assert experiment["ok"], experiment
    exp_id = experiment["experimental_project_id"]
    exp_root = app.project_path(exp_id)
    assert exp_root.exists()
    assert Path(experiment["initial_backup_path"]).exists()
    exp_status = app.experiment_status(exp_root)
    assert exp_status["role"] == "experimental"
    assert not exp_status["promotion_allowed"]
    exp_cfg = app.project_config(exp_id)
    assert exp_cfg["experimental_pipeline"]["quality_mode"] == "strict-original"
    assert exp_cfg["experimental_pipeline"]["full_configured_test_required"] is True
    assert exp_cfg["experimental_pipeline"]["allow_savestate_for_trusted_evidence"] is False

    # Targeted/shortcut evidence alone must never close feedback in strict mode.
    before_review = app.append_user_feedback(exp_root, "Strict quality smoke feedback.", "general")
    candidate = app.load_user_review(exp_root)
    candidate["feedback"][-1]["ready_for_verification"] = True
    candidate["feedback"][-1]["resolution"] = "Implemented in smoke fixture."
    candidate["feedback"][-1]["evidence"] = "Targeted diagnostic passed."
    app.save_user_review(exp_root, candidate)
    after_targeted_only = app.reconcile_feedback_work_orders(
        exp_root,
        before_review,
        {"configured": False, "ok": True},
        {"configured": False, "ok": True},
        verification_complete=True,
    )
    assert after_targeted_only["feedback"][-1]["addressed"] is False
    assert after_targeted_only["feedback"][-1]["ready_for_verification"] is True

    after_full_gate = app.reconcile_feedback_work_orders(
        exp_root,
        before_review,
        {"configured": True, "ok": True},
        {"configured": True, "ok": True},
        verification_complete=True,
    )
    assert after_full_gate["feedback"][-1]["addressed"] is True
    assert after_full_gate["feedback"][-1]["verification_class"] == "targeted-plus-original-full-regression"

    old_channel = os.environ.get("GAMEFORGE_BUILD_CHANNEL")
    os.environ["GAMEFORGE_BUILD_CHANNEL"] = "main"
    try:
        promoted = app.promote_experimental_copy(exp_id, True)
        assert promoted["ok"], promoted
        restored = app.project_path(cfg["id"])
        assert (restored / ".gameforge" / "promotion_receipt.json").exists()
        assert app.project_config(cfg["id"])["id"] == cfg["id"]
        assert Path(promoted["pre_promotion_backup_path"]).exists()
    finally:
        if old_channel is None:
            os.environ.pop("GAMEFORGE_BUILD_CHANNEL", None)
        else:
            os.environ["GAMEFORGE_BUILD_CHANNEL"] = old_channel

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
