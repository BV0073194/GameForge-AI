"""Durable, monotonic GameForge agent iteration accounting.

GameForge iterations and a game's own acceptance/progress iterations are
*different namespaces*. In particular, acceptance.json iteration=245 can
coexist with GameForge agent iteration=75. Never use the former to
increment the agent loop.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

_ITERATION_LOCK = threading.RLock()
_MAX_ITERATION = 1_000_000_000


def _read(path: Path) -> dict[str, Any]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def _number(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return result if 0 <= result <= _MAX_ITERATION else 0


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=True)
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path)


def iteration_snapshot(project: Path) -> dict[str, Any]:
    """Read known GameForge sources without trusting project-authored counts."""
    folder = project / ".gameforge"
    ledger = _read(folder / "iteration_state.json")
    evidence = _read(folder / "last_evidence.json")
    live = _read(folder / "live_activity.json")
    compact = _read(folder / "compact_state.json")
    delivery = _read(folder / "delivery_state.json")
    acceptance = _read(folder / "acceptance.json")
    sources = {
        "durable_ledger": _number(ledger.get("iteration")),
        "live_activity": _number(live.get("iteration")),
        "compact_state": _number(compact.get("iteration")),
        "last_evidence": _number(evidence.get("iteration")),
        "delivery_state": _number(delivery.get("iteration")),
    }
    current = max(sources.values(), default=0)
    verified = sources["last_evidence"]
    return {
        "agent_iteration": current,
        "last_evidence_iteration": verified,
        "unverified_iteration_gap": max(0, current - verified),
        "project_progress_iteration": _number(acceptance.get("iteration")),
        "sources": sources,
        "last_status": str(ledger.get("status") or live.get("status") or "unknown"),
        "last_started_at": ledger.get("last_started_at"),
        "last_finished_at": ledger.get("last_finished_at"),
        "status": str(ledger.get("status") or ""),
    }


def reserve_iteration(project: Path, *, maximum: int = 0) -> int | None:
    """Persist reservation *before* the turn, including turns later interrupted.

    Returns None at the limit without consuming an iteration. A fresh process
    recovers from the highest already-used GameForge counter.
    """
    with _ITERATION_LOCK:
        current = iteration_snapshot(project)["agent_iteration"]
        if maximum and current >= maximum:
            return None
        next_value = current + 1
        old = _read(project / ".gameforge" / "iteration_state.json")
        old.update({
            "version": 1,
            "iteration": next_value,
            "status": "running",
            "last_started_at": datetime.now(timezone.utc).isoformat(),
            "last_finished_at": None,
        })
        _write(project / ".gameforge" / "iteration_state.json", old)
        return next_value


def finish_iteration(project: Path, iteration: int, status: str) -> None:
    """Never decrease the reserved counter when older events arrive late."""
    if status not in {"running", "interrupted", "failed", "blocked", "paused", "tested", "stopped", "complete"}:
        raise ValueError("Unrecognized agent iteration status")
    with _ITERATION_LOCK:
        path = project / ".gameforge" / "iteration_state.json"
        ledger = _read(path)
        if _number(ledger.get("iteration")) > iteration:
            return
        ledger.update({
            "version": 1,
            "iteration": max(_number(ledger.get("iteration")), iteration),
            "status": status,
            "last_finished_at": datetime.now(timezone.utc).isoformat() if status != "running" else None,
        })
        _write(path, ledger)
