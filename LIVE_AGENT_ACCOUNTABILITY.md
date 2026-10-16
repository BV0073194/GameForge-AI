# GameForge: Live-Agent User-Input Accountability and Iteration Recovery

This note describes the live work-order and iteration recovery changes that
followed Fusion PR #8. Earlier GameForge versions could display user steering
as "delivered" when a Codex turn merely ended, and resume at the last *tested*
iteration even if newer Codex turns had failed.

## Work-order state machine

```text
received -> queued -> in_progress -> delivered_to_agent
                                    -> implemented -> verified
                                    -> [blocked by full quality gates]
queued/delivered_to_agent/implemented -> cancelled (only at the user's request)
in_progress -> queued (failed/interrupt/restart; never drop user text)
```

Every instruction has an immutable ID and text, sequence number, creation time,
attempt counter, optional linked feedback ID, and bounded status history. The
human-authored request remains pending until **verified** or cancelled. Old
`delivered` and `awaiting_verification` values migrate to
`delivered_to_agent` rather than being treated as complete.

The newest urgent instruction is the focus; otherwise the newest unfinished
user instruction takes precedence over optional roadmap/research work.
The exact focus instruction ID and text are injected at the **end** of the
prompt, even if the older project context is truncated. In-progress and
previously delivered but unimplemented requests remain in subsequent prompts.
When supported by Codex app-server, new feedback can be steered into the
current turn; ACP and `codex exec` use the durable queue instead.

## Delivery is not implementation

A successful Codex turn only changes `in_progress` to
`delivered_to_agent`. It does **not** prove an implementation.

The agent must submit a per-ID claim in
`.gameforge/live_instruction_results.json`:

```json
{
  "results": [
    {
      "id": "live-actual-id",
      "ready_for_verification": true,
      "resolution": "Gameplay code and asset changes, not mere acknowledgement",
      "evidence": "Specific checks and runtime observations",
      "changed_paths": ["workspace/source/gameplay.c"],
      "tests": [
        {
          "name": "Native weapon input test",
          "status": "passed",
          "log_path": "logs/weapon-input-test.log"
        }
      ]
    }
  ]
}
```

GameForge moves the item to **implemented** only if:

- the claim contains a matching outstanding ID, meaningful resolution/evidence
  and one or more valid existing project-local source files;
- all claimed changed source paths are present in the **actual production
  changes** observed by GameForge for the iteration, not simply old files;
- evidence remains linked to that work order instead of a generic agent result.

Targeted tests in the claim are explicitly **agent-reported** and displayed
as such. When a Git checkpoint is created, its revision and the pre-iteration
Git base are linked to the instruction's source changes.

GameForge moves it to **verified** only if the originally configured full
build **and** full test commands are both configured and successful; it records
their iteration and log paths. If the tests are absent or fail, the item stays
`implemented`. Full gates validate the configured regression, **not** every
possible gameplay requirement or subjective visual quality. Human acceptance
is still an independent check. Project completion is disallowed with any
remaining live work order.

## User feedback cannot disappear silently

The feedback API saves the original user wording to
`.gameforge/user_feedback_inbox.json` **before** updating the review file,
using an atomic serialized transaction and unique IDs. A concurrent or stale
Codex write that drops or rewrites a feedback entry is reconciled from the
inbox on the next read. Older projects have their existing feedback migrated
when first opened.

Submitting feedback also creates a linked live work order. When the normal
user-feedback work-order validator proves it addressed through the original
quality gates, its linked live item can be verified without duplicating the
implementation claim.

Existing `.gameforge/user_review.json` and `.gameforge/live_queue.json`
files are not removed or overwritten on upgrade. Cancelled work orders are
preserved in the history.

## Two different iteration counters

The OoT project snapshot legitimately contained two numbering systems:

- **GameForge agent iterations:** last evidence 73; live activity 75.
- **Game-authored/project progress:** `acceptance.json.iteration = 245`.

These counters are **not interchangeable**. The dashboard now labels both
instead of displaying contradictory unlabeled numbers.

Every new GameForge iteration gets a monotonic reservation saved in
`.gameforge/iteration_state.json` before checkpointing, prompting Codex or
calling build tools. On restart, the counter reconciles the durable ledger,
live activity, compact context, delivery state, last evidence, and available
Codex trace filenames (including failed turns). A restart does not silently
replay iteration 74 because iteration 73 was the last full build/test record.

The dashboard reports the last evidence iteration and a gap count when
newer started iterations do not yet have final build/test evidence. Game
progress in `acceptance.json.iteration` never affects the agent counter.

## Automated checks

The Windows and Ubuntu `GameForge Source Smoke` jobs exercise:

- old-state migration, interrupted/requeued instructions and live steering;
- explicit delivered/implemented/verified states and historical events;
- newest-instruction priority even when ISO timestamps have identical seconds;
- rejection of fabricated source-file changes and path traversal claims;
- implementation that remains unverified on a failing full regression;
- agent feedback HTTP delivery to the durable live queue;
- stale user-review overwrites and concurrent feedback submissions;
- crash-safe iteration numbering, real trace filename recovery and the
  245-versus-75 mismatch.

These are offline source and protocol tests. A live Codex/ACP session and
native packaged Windows executable still require validation on the installed
game-development computer. They are **not** implied by green CI.
