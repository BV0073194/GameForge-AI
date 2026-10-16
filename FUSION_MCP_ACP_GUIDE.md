# GameForge Fusion — MCP, ACP, and trustworthy live work orders

This implementation **re-creates supported behavior** observed in the user's
Melty 1.0.118 reference bundle. It does not copy proprietary Melty code,
install or authenticate a Melty service, or treat that bundle as a license.

## What is connected

- **Codex app-server**: persistent JSON-RPC session, thread resume, active-turn
  steer, interrupt, streamed task events, user questions, approval prompts,
  MCP server definitions on thread creation and JSON-RPC fallback.
- **Classic Codex exec**: preserves the prior compatible fallback. Installed
  Codex MCP configuration applies; GameForge project-level MCP entries are
  only passed to app-server and ACP, not silently applied to exec.
- **External ACP agent**: selectable local executable command and argument
  array. Implements ACP v1 initialize, session/new, session/prompt,
  session/update, session/cancel and session/request_permission. No shell
  is invoked for starting ACP. Since ACP v1 does not guarantee concurrent
  prompts, live steer is saved in the durable queue for the next turn.
- **MCP**: per-project streamable HTTP and stdio servers. Codex app-server
  receives its supported thread config; ACP receives MCP servers as
  session/new options. If the external agent does not support a server
  transport, the agent should report an error rather than claim it worked.
- **Human interaction**: ACP permission choices, Codex command/file change
  permissions, Codex tool questions and MCP elicitation forms are presented
  to the user. No unknown permission request is silently approved.
- **Instruction accountability**: `queued → in_progress → delivered_to_agent → implemented → verified` (or explicitly `cancelled`). A successful agent turn can acknowledge delivery, but cannot independently declare implementation or verification. Each item now carries its own audit history, production changed paths, targeted-test claims, original full-gate results and the Git checkpoint associated with the implementation.

## Configure an ACP agent

Open GameForge project **Settings -> AI execution engine**, choose
**External ACP agent** and provide an argument array for the locally installed
ACP-compatible executable, for example:

```json
["C:/Tools/my-agent.exe", "acp"]
```

The external agent must already be installed and authorized through its own
supported sign-in flow. GameForge does not download or sign in for it. If no
ACP executable is set, the agent blocks with a configuration error instead of
spending eight recovery iterations.

## Configure MCP

Open **Settings -> MCP tool servers**, supply a JSON array. Example:

```json
[
  {
    "name": "local-build-tools",
    "type": "stdio",
    "command": "C:/Tools/build-mcp.exe",
    "args": ["serve"],
    "env_vars": ["LOCAL_BUILD_TOKEN"],
    "enabled": true
  },
  {
    "name": "reference-tools",
    "type": "http",
    "url": "https://example.com/mcp",
    "bearer_token_env_var": "MY_MCP_TOKEN",
    "env_http_headers": {"X-Account": "MY_ACCOUNT_ID"},
    "enabled": true
  }
]
```

Set `MY_MCP_TOKEN` and other secret variables in the environment **before**
launching GameForge. Do not put literal passwords, API tokens or bearer
strings into `gameforge.json`. Validation rejects URLs with embedded
credentials, duplicate/invalid names and unrecognized transport types.
Existing user environment values are resolved in memory when initiating ACP
sessions and are not saved in project configuration.

Project-level MCP configuration changes require restarting the agent. Codex
app-server fingerprints the server configuration so a previously cached
thread is not resumed with stale tool servers.

**Compatibility note:** MCP stdio executables normally need an executable path
the target agent can resolve. ACP agents may require absolute paths. The
list of supported tools, model options and runtime capabilities depends on the
installed agent and MCP servers, not just GameForge.

## Live instruction verification contract

Every queued or steered user instruction has a persistent ID in
`.gameforge/live_queue.json`. Codex/ACP is asked to preserve evidence for
fulfilled items in `.gameforge/live_instruction_results.json`:

```json
{
  "results": [
    {
      "id": "live-actual-id",
      "ready_for_verification": true,
      "resolution": "What changed and why",
      "evidence": "Specific tests and runtime observations",
      "changed_paths": ["workspace/path-to-modified-source"],
      "tests": [
        {"name": "Weapon smoke test", "status": "passed", "log_path": "logs/weapon-smoke.log"}
      ]
    }
  ]
}
```

GameForge checks that the claim has a real instruction ID, non-empty
resolution and evidence, and actual modified project-local production paths.
A valid implementation claim moves the item to `implemented`, which remains
pending even when one of the full gates fails. The separate `verified` status
requires **both originally configured full build and test** to pass. The UI
shows per-instruction paths, agent-reported targeted tests, full-gate status,
status timeline and the Git checkpoint when available. A finished Codex turn
is never sufficient evidence, and the project cannot be declared complete
with pending live work orders.

For recovery, `.gameforge/iteration_state.json` records every GameForge
agent-iteration reservation before running Codex. It reconciles legacy
`live_activity.json`, `compact_state.json`, `last_evidence.json`, delivery
state and recent trace filenames. The separate game-authored
`acceptance.json.iteration` value is shown as **project progress** and is
never treated as GameForge's agent counter. See
[LIVE_AGENT_ACCOUNTABILITY.md](LIVE_AGENT_ACCOUNTABILITY.md) for details.

**Scope of verification:** these gates verify submitted implementation evidence
and the configured tests. They do not automatically prove that the game plays
exactly as the user intended. GameForge's independent acceptance/user-review
checks still apply. Write game-specific regression tests and runtime evidence
for gameplay-dependent changes.

## Gaps needing live integration tests

1. Signed-in Codex app-server MCP handshake on the user's installed version.
2. Real ACP executable (and ACP v2 changes, if needed).
3. Real MCP stdio and HTTP server authentication/permissions.
4. Native packaged Windows executable and process lifecycle.
5. High-load interaction races, restart recovery and cancellation semantics.
6. Game-specific quality and human verification beyond build/test success.
7. Advanced ACP UI content blocks (images, terminal/fs operations, auth
   handshakes, model selector) and MCP dynamic schema forms. The basic JSON
   elicitation UI handles simple objects and required fields, not the whole
   JSON Schema vocabulary.
8. Codex `exec` fallback project-specific MCP provisioning — today it
   intentionally relies on the installed Codex CLI configuration.

## Source and protocol references

- User-provided Melty 1.0.118 recovered reference (behavioral analysis only).
- [Agent Client Protocol](https://agentclientprotocol.com/), version 1 for this
  transport; v2 may require an adapter.
- [Codex GitHub repository](https://github.com/openai/codex).

Automated offline tests cover MCP validation, ACP handshake, streamed events,
human permission requests, cancellation and live work-order bookkeeping on
Windows and Ubuntu. A passing source smoke check is not evidence of a complete
end-to-end live integration test.
