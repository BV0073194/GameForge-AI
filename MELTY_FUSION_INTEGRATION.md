# GameForge Fusion: Melty research and integration contract

Research date: 2026-10-14. Source: user-provided Melty 1.0.118 installer, extracted `app.asar` / `dist/main.bundle.mjs`. This document records protocol behavior, not a license grant to copy distribution code.

## Verified Melty protocol observations

Recovered distribution contains Codex app-server JSON-RPC operations `thread/start`, `turn/start`, `turn/steer`, and `turn/interrupt`. Steering includes a thread identifier, user input and an expected turn identifier. It also contains ACP-like `session/prompt`, `session/update` and `session/cancel` paths. These are observations from the shipped bundle; exact current Codex protocol schema must be validated against the installed Codex CLI at runtime.

## Existing GameForge assets to retain

- `GameForgeAI/server/app.py`: durable live instruction queue, `interrupt_agent_and_restart`, autonomous agent loop, build/test and runtime acceptance checks, Git checkpoint and rollback.
- `GameForgeAI/web/app.js`: queue/interrupt controls, agent question responses, live activity and runtime status.
- `GameForgeAI/tests/smoke.py`: queue ordering, requeue on interruption, agent-answer enqueue, reversible Fusion deployment.
- Portable `.gfai` project contract and existing dashboard layout.

## Backend architecture to implement

Introduce an `AgentTransport` boundary, independent of game-specific QA:

1. `CodexAppServerTransport` owns a persistent subprocess and JSON-RPC stdin/stdout reader; tracks thread ID, turn ID, capabilities and pending requests. Serializes outbound writes and correlates request IDs with responses.
2. `CodexExecTransport` preserves existing `codex exec --json` as fallback when app-server handshake fails or required methods are unsupported.
3. Optionally `AcpTransport` for third-party agents that advertise ACP; do not assume every agent supports in-turn steering.
4. `AgentSupervisor` owns cancellation and child-process cleanup, queue claiming, task transitions and durable event history.
5. GameForge's existing build/test/launch/visual/regression/acceptance loop remains the source of truth for completion.

### Steering and interrupt semantics

- **Queue next**: atomically persist instruction, acknowledge its durable ID, and dispatch at the next turn boundary.
- **Steer active turn**: if transport explicitly supports steering and a turn is active, send the instruction with the active turn ID; on rejection, enqueue without losing it.
- **End current task & run now**: persist high-priority instruction *before* cancellation; issue `turn/interrupt` (or transport-specific cancel), await bounded completion, then terminate process tree on timeout, reconcile in-flight queue items and start the priority instruction. Never claim completion until the replacement turn is actually started.
- Preserve partially edited project files, and run the existing Git/regression gates before declaring any result accepted.
- Serialize per-project state transitions to prevent simultaneous agent loops or double-claimed instructions.
- Treat late events from an interrupted turn as stale using generation IDs.

### Agent questions

When the protocol requests user input, create a durable question record with request ID and answer schema. Show it in the existing GameForge question UI; answer the *same protocol request* while it is pending. Existing queue-based answers remain the fallback for agents without interactive requests. Do not send empty automatic answers.

### Safety and reliability

Bound message size and queue growth; redact auth tokens from logs; validate project-scoped paths; prevent arbitrary renderer-to-OS command execution; avoid loading untrusted web content into privileged Electron contexts. Persist every state transition. Distinguish `queued`, `steering`, `interrupting`, `waiting-for-answer`, `running`, `verifying`, `failed`, and `complete`.

## Acceptance tests required before replacing the existing transport

1. App-server handshake succeeds against installed Codex CLI; unsupported versions fall back without dropping instructions.
2. Queue instruction while turn is running; exactly-once dispatch at boundary.
3. Steer supported turn and verify agent sees instruction before completion.
4. Interrupt a long-running turn; measure cancellation latency, assert process cleanup and priority execution.
5. Race simultaneous queue/interrupt/stop; no duplicate tasks or lost instructions.
6. Answer real interactive question, including timeout and cancel scenarios.
7. Restart application mid-turn and recover durable queued work without falsely marking completion.
8. Run build/test/runtime/acceptance gates after interruption and preserve last known-good checkpoint.
9. Native Windows frozen executable integration test, not just source smoke.
10. UI accessibility: keyboard, narrow viewport, reduced motion, status announcements.

## Implemented on the Fusion branch

- Added `server/codex_app_server.py` for persistent JSON-RPC Codex sessions: handshake, thread resume, streamed turns, in-flight steering, interruption and child-process cleanup.
- Wired GameForge to prefer app-server, with the original `codex exec` preserved as a fallback when the initial handshake fails. Active turn failures are never silently replayed.
- Wired `live/queue`, `live/steer`, `live/interrupt`, agent-question responses, command/file approval requests and priority work scheduling into the existing GameForge dashboard.
- Preserved GameForge's original build/test/runtime/evidence/acceptance loop and reversible Git checkpoints.
- Added transaction locking and unique IDs to the durable queue. Cached successful Codex inference preflight for 30 minutes to reduce redundant work.
- Added a project-level execution engine selector and upgraded responsive visuals and accessibility.
- Added offline simulated app-server tests and cross-platform CI coverage (Windows + Ubuntu) including JavaScript parsing checks.

## Outstanding live verification

- Tests use a simulated app-server. A real signed-in Codex session has not yet been exercised against this branch, nor has a native packaged executable been tested.
- Command/file approvals and Codex tool questions are bridged; advanced permission requests and MCP elicitation remain unsupported and default to rejection.
- A failed app-server handshake falls back to CLI. An error after turn start is reported rather than blindly replaying edits.
- The original PR #7 was merged in October 2026; its source smoke tests were green, but real Codex/native Windows validation remained outstanding. Treat this as a record of the original integration, not a current merge gate.

## Automatic project-scoped WSL cleanup

After each completed iteration, the existing artifact cleanup also checks for a
WSL project worktree. It may discover the `mod=/absolute/path` value from
`workspace/tools/build_mod.sh` and the distro from `build_mod.ps1`, or use
`gameforge.json` cleanup settings `wsl_project_root` and `wsl_distro`.
The worktree must contain a GameForge-owned `.gameforge/` directory.

Only old files in `.gameforge/tmp`, `.gameforge/temp`, `.gameforge/cache`,
and `.gameforge/scratch` are pruned (default minimum age: 48 hours). The
cleaner never runs `apt clean`, `docker system prune`, `make clean`, or
broad deletions of WSL home directories, compilers, toolchains, build outputs,
research evidence, game assets, or user-owned caches. If the marker or WSL
environment is missing, cleanup skips safely and records why in
`.gameforge/last_cleanup.json`.

Set `cleanup.wsl_cleanup_enabled=false` to disable, or
`cleanup.wsl_min_age_hours` to increase the retention age.

## Follow-on integration: ACP, MCP and instruction verification

The newer Fusion integration adds an external ACP v1 agent transport, project-scoped MCP server configuration for Codex/ACP, interactive MCP elicitation and ACP permission requests, Codex model and effort controls, and a durable `awaiting_verification` state for live instructions. It requires actual production file changes and original configured build/test gates before recording verified work orders. See [FUSION_MCP_ACP_GUIDE.md](FUSION_MCP_ACP_GUIDE.md) for configuration, compatibility limitations and open end-to-end test requirements. This is an independent implementation based on protocol observations rather than a copy of Melty's distribution code.
