"""Regression coverage for durable user work orders and iteration recovery."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import app
from server.iteration_state import (
    iteration_snapshot, reserve_iteration, finish_iteration,
)


class IterationLedgerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.p = Path(self.td.name)
        (self.p / ".gameforge").mkdir()

    def tearDown(self):
        self.td.cleanup()

    def seed(self):
        folder = self.p / ".gameforge"
        for name, value in (
            ("acceptance.json", {"iteration": 245, "project_complete": False}),
            ("last_evidence.json", {"iteration": 73}),
            ("live_activity.json", {"iteration": 75, "status": "running"}),
            ("compact_state.json", {"iteration": 74}),
            ("delivery_state.json", {"iteration": 72}),
        ):
            (folder / name).write_text(json.dumps(value), encoding="utf-8")

    def test_agent_versus_game_progress_never_collapsed(self):
        self.seed()
        snap = iteration_snapshot(self.p)
        self.assertEqual(snap["agent_iteration"], 75)
        self.assertEqual(snap["project_progress_iteration"], 245)
        self.assertEqual(snap["last_evidence_iteration"], 73)
        self.assertEqual(snap["unverified_iteration_gap"], 2)
        self.assertEqual(reserve_iteration(self.p), 76)
        self.assertTrue((self.p / ".gameforge/iteration_state.json").exists())
        finish_iteration(self.p, 76, "failed")
        self.assertEqual(reserve_iteration(self.p), 77)
        finish_iteration(self.p, 76, "tested")  # late event must not overwrite
        snap = iteration_snapshot(self.p)
        self.assertEqual(snap["agent_iteration"], 77)
        self.assertEqual(snap["last_status"], "running")
        self.assertIsNone(reserve_iteration(self.p, maximum=77))

    def test_concurrent_reservations_are_unique_and_monotonic(self):
        self.seed()
        with ThreadPoolExecutor(max_workers=10) as executor:
            ids = list(executor.map(lambda _: reserve_iteration(self.p), range(25)))
        self.assertEqual(sorted(ids), list(range(76, 101)))
        self.assertEqual(iteration_snapshot(self.p)["agent_iteration"], 100)

    def test_legacy_trace_names_reserve_without_replaying_failed_turns(self):
        self.seed()
        logs = self.p / "logs"
        logs.mkdir()
        (logs / "codex-iteration-0081.jsonl").write_text("", encoding="utf-8")
        (logs / "codex-iteration-0080.final.txt").write_text("failed", encoding="utf-8")
        (logs / "codex-iteration-not-valid.jsonl").write_text("", encoding="utf-8")
        self.assertEqual(iteration_snapshot(self.p)["agent_iteration"], 81)
        self.assertEqual(reserve_iteration(self.p), 82)

    def test_malformed_legacy_snapshots_cannot_reset_or_jump(self):
        folder = self.p / ".gameforge"
        (folder / "acceptance.json").write_text('{"iteration": 99999999}', encoding="utf-8")
        (folder / "last_evidence.json").write_text('{"iteration": -99}', encoding="utf-8")
        (folder / "live_activity.json").write_text('{"iteration": "not a number"}', encoding="utf-8")
        (folder / "compact_state.json").write_text('{"iteration": true}', encoding="utf-8")
        self.assertEqual(iteration_snapshot(self.p)["agent_iteration"], 0)
        self.assertEqual(reserve_iteration(self.p), 1)


class LiveWorkOrderTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.p = Path(self.td.name)
        (self.p / ".gameforge").mkdir()
        (self.p / "workspace").mkdir()

    def tearDown(self):
        self.td.cleanup()

    def _status(self, item):
        return next(x for x in app.load_live_queue(self.p)["items"] if x["id"] == item["id"])

    def _prepare(self, text="Add an actual gameplay feature."):
        item = app.enqueue_live_instruction(self.p, text)
        claimed = app.claim_live_instructions(self.p, 1)
        self.assertEqual(claimed[0]["id"], item["id"])
        app.settle_live_instructions(self.p, 1, delivered=True)
        self.assertEqual(self._status(item)["status"], "delivered_to_agent")
        return item

    def test_legacy_delivery_migration_preserves_user_input(self):
        legacy = {"version": 2, "items": [
            {"id": "live-old", "text": "My unimplemented instruction.",
             "status": "delivered", "created_at": "2026-10-15T01:00:00Z"}
        ]}
        app.write_json(app.live_queue_path(self.p), legacy)
        visible = app.live_queue_public(self.p)
        self.assertEqual(visible["delivered_count"], 1)
        self.assertEqual(visible["delivered_to_agent"][0]["text"], "My unimplemented instruction.")
        self.assertFalse(visible["recent"])

    def test_new_user_instruction_preempts_older_normal_work(self):
        older = app.enqueue_live_instruction(self.p, "Older task")
        newer = app.enqueue_live_instruction(self.p, "Newest task")
        self.assertEqual(app.live_queue_public(self.p)["focus_id"], newer["id"])
        urgent = app.enqueue_live_instruction(self.p, "Urgent task", mode="interrupt")
        self.assertEqual(app.live_queue_public(self.p)["focus_id"], urgent["id"])
        self.assertEqual(app.claim_live_instructions(self.p, 5)[0]["id"], urgent["id"])
        self.assertEqual(app.live_queue_public(self.p)["focus_id"], urgent["id"])
        app.requeue_live_instructions(self.p, reason="interrupted")
        self.assertEqual(self._status(urgent)["status"], "queued")
        self.assertGreaterEqual(len(self._status(urgent)["history"]), 3)

    def test_live_steer_is_accepted_but_not_implemented(self):
        item = app.enqueue_live_instruction(self.p, "Steer turn, do not falsely finish")
        self.assertTrue(app.mark_live_instruction_steered(self.p, item["id"]))
        self.assertFalse(app.mark_live_instruction_steered(self.p, item["id"]))
        self.assertEqual(self._status(item)["status"], "delivered_to_agent")
        self.assertIsNone(self._status(item).get("verification_claim"))

    def test_implementation_then_full_test_verification(self):
        item = self._prepare()
        source = self.p / "workspace" / "gameplay.py"
        source.write_text("def fire(): return True\n", encoding="utf-8")
        log = self.p / "logs" / "shot-test.log"
        log.parent.mkdir()
        log.write_text("fire smoke passed", encoding="utf-8")
        app.write_json(self.p / ".gameforge/live_instruction_results.json", {"results": [{
            "id": item["id"], "ready_for_verification": True,
            "resolution": "Implemented a real gameplay behavior for the requested change.",
            "evidence": "Completed targeted gameplay checks with preserved trace output.",
            "changed_paths": ["workspace/gameplay.py"],
            "tests": [{"name": "Fire smoke", "status": "passed", "log_path": "logs/shot-test.log"}],
        }]})
        bad_gates = app.reconcile_live_instruction_results(
            self.p, 1, {"configured": True, "ok": True},
            {"configured": True, "ok": False},
            {"production_paths": ["workspace/gameplay.py"]},
        )
        self.assertIn(item["id"], bad_gates["implemented_ids"])
        self.assertNotIn(item["id"], bad_gates["verified_ids"])
        progress = self._status(item)
        self.assertEqual(progress["status"], "implemented")
        self.assertEqual(progress["verification_claim"]["tests"][0]["log_path"], "logs/shot-test.log")
        self.assertTrue(progress["last_full_gates"]["build"]["passed"])
        self.assertFalse(progress["last_full_gates"]["test"]["passed"])
        app.link_live_instruction_checkpoint(self.p, 1, "base-rev", "new-git-rev")
        self.assertEqual(self._status(item)["verification_claim"]["git_checkpoint"], "new-git-rev")
        self.assertEqual(self._status(item)["verification_claim"]["git_diff_base"], "base-rev")
        good_gates = app.reconcile_live_instruction_results(
            self.p, 2, {"configured": True, "ok": True},
            {"configured": True, "ok": True}, {"production_paths": []},
        )
        self.assertIn(item["id"], good_gates["verified_ids"])
        done = self._status(item)
        self.assertEqual(done["status"], "verified")
        self.assertEqual(done["verification_iteration"], 2)
        events = [h["status"] for h in done["history"]]
        self.assertEqual(events[:4], ["queued", "in_progress", "delivered_to_agent", "implemented"])
        self.assertEqual(events[-1], "verified")

    def test_unrelated_or_path_escape_claim_does_not_implement(self):
        item = self._prepare()
        source = self.p / "workspace" / "gameplay.py"
        source.write_text("new code\n", encoding="utf-8")
        results_path = self.p / ".gameforge/live_instruction_results.json"
        claim = {
            "id": item["id"], "ready_for_verification": True,
            "resolution": "An unsupported claim for source changes that did not happen.",
            "evidence": "A test summary without matching production file changes.",
            "changed_paths": ["workspace/gameplay.py"],
        }
        app.write_json(results_path, {"results": [claim]})
        report = app.reconcile_live_instruction_results(
            self.p, 1, {"configured": True, "ok": True},
            {"configured": True, "ok": True}, {"production_paths": ["workspace/other.py"]},
        )
        self.assertFalse(report["implemented_ids"])
        self.assertEqual(self._status(item)["status"], "delivered_to_agent")
        claim["changed_paths"] = ["../outside.py"]
        app.write_json(results_path, {"results": [claim]})
        report = app.reconcile_live_instruction_results(
            self.p, 1, {"configured": True, "ok": True},
            {"configured": True, "ok": True}, {"production_paths": ["../outside.py"]},
        )
        self.assertFalse(report["verified_ids"])
        self.assertEqual(self._status(item)["status"], "delivered_to_agent")

    def test_new_focus_is_in_prompt_even_with_old_delivered_work(self):
        old = self._prepare("A previously delivered unfinished feature")
        new = app.enqueue_live_instruction(self.p, "The newest user requirement.")
        cfg = {"goal": "A playable game", "research_mode": "off",
               "iteration_pipeline": {"enabled": True, "compact_context": True}}
        prompt = app.build_agent_prompt(self.p, cfg, 2, None, None, None)
        self.assertIn("MANDATORY CURRENT USER WORK ORDER", prompt)
        self.assertIn(new["id"], prompt.split("MANDATORY CURRENT USER WORK ORDER")[-1])
        self.assertIn(old["id"], prompt)
        self.assertEqual(app.live_queue_public(self.p)["focus_id"], new["id"])

    def test_feedback_inbox_recovers_stale_agent_overwrite(self):
        submitted = app.append_user_feedback(self.p, "User asked for a full rifle mod.", "gameplay")
        original = submitted["feedback"][-1]
        self.assertTrue(app.user_feedback_inbox_path(self.p).exists())
        # Model writes an obsolete snapshot, accidentally deleting the user entry.
        app.write_json(app.user_review_path(self.p), {"user_done": False, "feedback": []})
        recovered = app.load_user_review(self.p)["feedback"]
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["id"], original["id"])
        self.assertEqual(recovered[0]["text"], original["text"])
        self.assertFalse(recovered[0]["addressed"])
        # Even if the model rewrites the wording, the stored original wins.
        recovered[0]["text"] = "The model replaced the user's request"
        app.save_user_review(self.p, {"feedback": recovered})
        self.assertEqual(app.load_user_review(self.p)["feedback"][0]["text"], original["text"])

    def test_parallel_feedback_submission_keeps_every_message(self):
        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(
                lambda i: app.append_user_feedback(self.p, f"User request number {i}", "gameplay"),
                range(40),
            ))
        self.assertEqual(len(results), 40)
        final = app.load_user_review(self.p)["feedback"]
        self.assertEqual(len(final), 40)
        self.assertEqual(len({x["id"] for x in final}), 40)
        self.assertEqual({x["text"] for x in final},
                         {f"User request number {i}" for i in range(40)})
        app.write_json(app.user_review_path(self.p), {"feedback": []})
        self.assertEqual(len(app.load_user_review(self.p)["feedback"]), 40)

    def test_latest_feedback_beats_stale_delivery_state(self):
        app.write_json(self.p / ".gameforge/user_review.json", {
            "user_done": False, "feedback": [
                {"id": "feedback-older", "text": "An older user request",
                 "created_at": "2026-10-15T18:17:06Z", "addressed": False},
                {"id": "feedback-newer", "text": "The latest urgent feedback",
                 "created_at": "2026-10-15T18:17:06Z", "addressed": False},
            ],
        })
        app.write_json(self.p / ".gameforge/delivery_state.json", {
            "focus_feedback_id": "feedback-older",
            "consecutive_diagnostic_only": 3,
        })
        state = app.delivery_state_for_prompt(self.p, app.load_user_review(self.p))
        self.assertEqual(state["focus_feedback_id"], "feedback-newer")
        cfg = {"goal": "Playable game", "research_mode": "off",
               "iteration_pipeline": {"enabled": True, "compact_context": True}}
        prompt = app.build_agent_prompt(self.p, cfg, 1, None, None)
        self.assertIn("MANDATORY CURRENT USER FEEDBACK", prompt)
        self.assertIn("feedback-newer", prompt.split("MANDATORY CURRENT USER FEEDBACK")[-1])

    def test_linked_feedback_cannot_be_falsely_closed(self):
        item = app.enqueue_live_instruction(self.p, "Use original user feedback",
            source="user-feedback", metadata={"feedback_id": "feedback-test"})
        app.claim_live_instructions(self.p, 1)
        app.settle_live_instructions(self.p, 1, delivered=True)
        app.write_json(self.p / ".gameforge/user_review.json", {
            "feedback": [{
                "id": "feedback-test", "addressed": False, "status": "pending",
                "resolution": "", "evidence": "",
            }]
        })
        app.reconcile_live_instruction_results(
            self.p, 1, {"configured": True, "ok": True},
            {"configured": True, "ok": True}, {"production_paths": []})
        self.assertEqual(self._status(item)["status"], "delivered_to_agent")
        review = app.load_user_review(self.p)
        review["feedback"][0].update({
            "addressed": True, "status": "addressed",
            "resolution": "A verified feature", "evidence": "Full runtime and regression",
        })
        app.save_user_review(self.p, review)
        app.reconcile_live_instruction_results(
            self.p, 2, {"configured": True, "ok": True},
            {"configured": True, "ok": True}, {"production_paths": ["workspace/code.py"]})
        self.assertEqual(self._status(item)["status"], "verified")


if __name__ == "__main__":
    unittest.main()
