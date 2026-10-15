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
    assert (p / "design" / "project.json").is_file()
    assert (p / "tasks" / "MVP.md").is_file()
    fusion_design = app.read_json(p / "design" / "project.json", {})
    assert fusion_design["format"] == "GameForgeAI.FusionProject"
    assert "configured original full regression passes" in fusion_design["release_gates"]

    # The strict fast pipeline is now production behavior on main. Targeted
    # diagnostics may accelerate iteration, but they cannot close feedback or
    # completion without the configured full build/test quality gate.
    production_cfg = app.project_config(cfg["id"])
    pipeline = app.iteration_pipeline_settings(production_cfg)
    assert pipeline["quality_mode"] == "strict-original"
    assert pipeline["full_configured_test_required"] is True
    assert pipeline["allow_savestate_for_trusted_evidence"] is False

    # Prompt construction itself is runtime-critical. Keep JSON examples inside
    # the f-string escaped so Start/Continue cannot fail before Codex launches.
    prompt_smoke = app.build_agent_prompt(p, production_cfg, 1, None, None, None)
    assert '.gameforge/cleanup_candidates.json' in prompt_smoke
    assert '{"path":"relative/path","safe_to_delete":true' in prompt_smoke
    assert "LIVE FUSION INTERACTION" in prompt_smoke
    assert "FUSION RUNTIME" in prompt_smoke

    # Fusion live steering is durable, priority ordered, and injected into the
    # next coding-agent prompt without weakening the normal quality gates.
    queued_normal = app.enqueue_live_instruction(p, "Do this after the current turn.", mode="queue")
    queued_now = app.enqueue_live_instruction(p, "Do this immediately.", mode="interrupt")
    claimed = app.claim_live_instructions(p, 2)
    assert claimed[0]["id"] == queued_now["id"], claimed
    assert {x["id"] for x in claimed} >= {queued_normal["id"], queued_now["id"]}
    app.settle_live_instructions(p, 2, delivered=True)
    assert app.live_queue_public(p)["queued_count"] == 0

    # Race regression: concurrent API-style queue submissions must not overwrite
    # each other or generate identical IDs.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=12) as pool:
        parallel = list(pool.map(
            lambda i: app.enqueue_live_instruction(p, f"Parallel request {i}"),
            range(48)
        ))
    assert len({item["id"] for item in parallel}) == 48
    queued_parallel = app.live_queue_public(p)["queued"]
    assert {item["id"] for item in parallel}.issubset({x["id"] for x in queued_parallel})
    batch = app.claim_live_instructions(p, 20, limit=64)
    assert len(batch) == 48
    app.settle_live_instructions(p, 20, delivered=True)
    assert app.live_queue_public(p)["queued_count"] == 0

    steered = app.enqueue_live_instruction(p, "Steer in flight")
    assert app.mark_live_instruction_steered(p, steered["id"])
    assert not app.mark_live_instruction_steered(p, steered["id"])
    assert app.live_queue_public(p)["queued_count"] == 0

    retry_item = app.enqueue_live_instruction(p, "Do not lose me if interrupted.", mode="queue")
    retry_claim = app.claim_live_instructions(p, 3)
    assert any(x["id"] == retry_item["id"] for x in retry_claim)
    app.requeue_live_instructions(p, reason="smoke interrupt")
    assert any(x["id"] == retry_item["id"] for x in app.live_queue_public(p)["queued"])

    prompt_item = app.enqueue_live_instruction(p, "Use the live steering message in this turn.", mode="queue")
    prompt_live = app.build_agent_prompt(p, production_cfg, 4, None, None, None)
    assert "LIVE USER INSTRUCTIONS" in prompt_live
    assert "Use the live steering message in this turn." in prompt_live
    app.settle_live_instructions(p, 4, delivered=True)
    assert any(x["id"] == prompt_item["id"] and x["status"] == "delivered"
               for x in app.load_live_queue(p)["items"])

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

    # Wrapped zeldaret/oot projects can infer the official build-dir-only clean
    # command without requiring an existing project's config to have been migrated.
    oot_cfg = app.project_config(cfg["id"])
    oot_cfg["goal"] = "Modify the current zeldaret/oot decomp."
    oot_cfg["commands"]["clean"] = ""
    tools_dir = p / "workspace" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / "build_mod.sh").write_text(
        "#!/usr/bin/env bash\n"
        "mod=/home/test/oot-mod\n"
        "make all VERSION=ntsc-1.0 REGION=US COMPARE=0 NON_MATCHING=0 -j4\n",
        encoding="utf-8",
    )
    (tools_dir / "build_mod.ps1").write_text(
        "& wsl -d Ubuntu --exec bash /tmp/build_mod.sh\n", encoding="utf-8"
    )
    inferred_clean = app.infer_clean_command(p, oot_cfg)
    assert "wsl -d Ubuntu --exec bash -lc" in inferred_clean, inferred_clean
    assert "cd /home/test/oot-mod && make clean VERSION=ntsc-1.0 REGION=US" in inferred_clean, inferred_clean

    # Project commands are serialized so a manual Build cannot collide with an
    # agent/test build and leave WSL compiler executables busy.
    blocker_script = p / "smoke_blocker.py"
    blocker_script.write_text("import time\ntime.sleep(2)\n", encoding="utf-8")
    first_result = {}
    def run_blocker():
        first_result.update(app.run_shell(f'"{sys.executable}" smoke_blocker.py', p, timeout=10))
    blocker_thread = threading.Thread(target=run_blocker, daemon=True)
    blocker_thread.start()
    deadline = time.time() + 3
    while time.time() < deadline:
        lock = app._project_command_lock(p)
        if not lock.acquire(blocking=False):
            break
        lock.release()
        time.sleep(0.05)
    overlapping = app.run_shell(f'"{sys.executable}" -c "print(1)"', p, timeout=5)
    assert overlapping.get("busy") is True, overlapping
    blocker_thread.join(timeout=5)
    assert first_result.get("ok") is True, first_result

    # A short-lived Text-file-busy failure is retried automatically instead of
    # being surfaced as a permanent build failure.
    transient_script = p / "smoke_transient_busy.py"
    transient_script.write_text(
        "from pathlib import Path\n"
        "m=Path('transient.marker')\n"
        "if not m.exists():\n"
        "    m.write_text('1')\n"
        "    print('cp: Text file busy')\n"
        "    raise SystemExit(1)\n"
        "print('retry ok')\n",
        encoding="utf-8",
    )
    transient = app.run_shell(f'"{sys.executable}" smoke_transient_busy.py', p, timeout=10)
    assert transient["ok"] is True, transient
    assert transient.get("transient_retries") == 1, transient

    # Melty-style local run reports become Fusion evidence while GameForge
    # remains the authority for strict build/test acceptance.
    launch_script = p / "smoke_launch.py"
    launch_script.write_text("print('fusion launch ok')\n", encoding="utf-8")
    cfg_run = app.project_config(cfg["id"])
    cfg_run["commands"]["launch"] = f'"{sys.executable}" smoke_launch.py'
    app.write_json(p / "gameforge.json", cfg_run)
    launched = app.start_managed_process(cfg["id"])
    assert launched["ok"], launched
    deadline = time.time() + 8
    managed = launched
    while time.time() < deadline:
        managed = app.managed_process_public(cfg["id"])
        if not managed.get("running"):
            break
        time.sleep(0.1)
    assert managed.get("returncode") == 0, managed
    reports = app.load_run_reports(p)["reports"]
    assert reports and reports[-1]["worked"] is True, reports
    manifest = app.fusion_manifest(p, app.project_config(cfg["id"]))
    assert manifest["format"] == "GameForgeAI.Fusion"
    assert manifest["recent_run_reports"][-1]["worked"] is True

    # Fusion deployment provides the Melty-style reversible install property:
    # replace a file only after backing it up, then restore the exact original.
    game_root = Path(td) / "owned-game"
    game_target = game_root / "mods" / "example.dat"
    game_target.parent.mkdir(parents=True, exist_ok=True)
    game_target.write_text("original-game-file", encoding="utf-8")
    built_file = p / "release" / "example.dat"
    built_file.parent.mkdir(parents=True, exist_ok=True)
    built_file.write_text("fusion-built-file", encoding="utf-8")
    app.write_json(app.fusion_deploy_config_path(p), {
        "target_root": str(game_root),
        "files": [{"source": "release/example.dat", "target": "mods/example.dat"}],
    })
    install = app.fusion_install(cfg["id"])
    assert install["ok"], install
    assert game_target.read_text(encoding="utf-8") == "fusion-built-file"
    assert app.fusion_deployment_status(p)["state"]["status"] == "active"
    restore = app.fusion_uninstall(cfg["id"])
    assert restore["ok"], restore
    assert game_target.read_text(encoding="utf-8") == "original-game-file"
    assert app.fusion_deployment_status(p)["state"]["status"] == "restored"

    # If the installed file changes after deployment, restore must refuse to
    # overwrite it. This preserves user/game changes instead of blindly rolling back.
    game_target.write_text("original-game-file-2", encoding="utf-8")
    install2 = app.fusion_install(cfg["id"])
    assert install2["ok"], install2
    game_target.write_text("changed-after-install", encoding="utf-8")
    restore_conflict = app.fusion_uninstall(cfg["id"])
    assert restore_conflict["ok"] is False, restore_conflict
    assert restore_conflict["conflicts"], restore_conflict
    assert game_target.read_text(encoding="utf-8") == "changed-after-install"
    assert app.fusion_deployment_status(p)["state"]["status"] == "active-with-conflicts"

    # Reset the fixture so later smoke work is not left with an active deployment.
    state_reset = app.read_json(app.fusion_deployment_state_path(p), {})
    state_reset["status"] = "restored"
    app.write_json(app.fusion_deployment_state_path(p), state_reset)

    inventory = app.discover_installed_games()
    assert inventory["local_only"] is True
    assert isinstance(inventory["games"], list)
    app.write_json(p / ".gameforge" / "game_inventory.json", inventory)

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

        # Agent questions feed their answers back into the same durable live
        # queue used for user steering.
        app.write_json(app.user_input_request_path(p), {
            "id": "smoke-question",
            "status": "pending",
            "kind": "text",
            "title": "Which option?",
            "message": "Choose the smoke option.",
            "resume_after_submit": False,
        })
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/project/{cfg['id']}/input-request/respond",
            data=json.dumps({"value": "option-a"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            answer_result = json.loads(r.read())
            assert answer_result["ok"] is True
        answer_items = app.load_live_queue(p)["items"]
        assert any(x.get("source") == "agent-answer" and "option-a" in x.get("text", "")
                   for x in answer_items), answer_items

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/project/{cfg['id']}/state", timeout=5) as r:
            state_payload = json.loads(r.read())
            assert "live_queue" in state_payload
            assert state_payload["fusion_manifest"]["format"] == "GameForgeAI.Fusion"
            assert "fusion_deployment" in state_payload
            assert "game_inventory" in state_payload
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            page = r.read().decode("utf-8", "replace")
            assert "GameForge" in page
    finally:
        server.shutdown()
print("SMOKE_OK")
