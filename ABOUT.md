# GameForge AI — Exhaustive Technical About / Maintainer / AI Repair Guide

This file is intentionally detailed.

Its purpose is to give a new developer or AI agent enough context to reason about GameForge itself **without having to rediscover the architecture from scratch**.

When repairing GameForge, treat this document as explanatory context, but treat the actual source code as the final authority when a discrepancy exists.

---

# 1. Identity

**Project name:** GameForge AI

**Current development family:** v1.0

**Current stabilization marker:** v1.0.4

**Application type:** local desktop-oriented web application packaged as a native single-file executable.

**Primary domain:** autonomous video-game development and modification.

**Not a general-purpose automation agent.**

---

# 2. Core mission

GameForge exists to bridge the gap between:

```text
"AI generated some code"
```

and:

```text
"a real playable game/mod/build was produced, launched, observed, tested, repaired, and regression-checked."
```

The central premise is that game development is an iterative empirical process.

The system therefore treats source generation as only one step in a larger control loop.

The desired complete loop is:

```text
goal
→ requirements
→ research
→ source/toolchain discovery
→ plan
→ checkpoint
→ implementation
→ build
→ launch
→ automated interaction
→ logs
→ visual observation
→ performance observation
→ acceptance evaluation
→ diagnosis
→ repair
→ regression testing
→ checkpoint
→ next milestone
→ release
```

---

# 3. Non-goals

GameForge should not be described as capable of literally doing anything.

It does not make impossible host/platform restrictions disappear.

It does not legally redistribute commercial game content.

It does not automatically possess proprietary SDKs.

It does not make unsupported engine APIs exist.

It does not transform closed-source binary games into source code by magic.

It does not guarantee that every arbitrary prompt can be implemented exactly.

It does not consider a successful compile proof of gameplay correctness.

---

# 4. Fundamental invariants

Any AI or developer modifying the core should preserve these unless deliberately changing the product architecture.

## 4.1 Game-only scope

The autonomous agent contract is for video-game development work.

## 4.2 Project state lives outside the executable

The application executable should be replaceable/upgradable without destroying projects.

## 4.3 User uploads are inputs

Do not destructively rewrite original uploads.

Create derivatives in working/project paths.

## 4.4 No fabricated success

Never mark an acceptance requirement pass merely because the code appears correct.

## 4.5 Git is a safety boundary

Autonomous work should be reversible.

## 4.6 Acceptance is explicit

Completion is governed by `.gameforge/acceptance.json`.

## 4.7 Real blockers are valid outcomes

If a required API/tool/hardware capability genuinely does not exist, record that rather than faking completion.

## 4.8 Public/authorized research only

Do not make stolen/private source, leaked proprietary code, credentials, or pirated binaries dependencies.

## 4.9 Preserve regressions

A new feature that breaks a previously accepted required feature is not a successful milestone.

---

# 5. Current source tree

The minimal release source should contain:

```text
GameForgeAI/
├── .github/
│   └── workflows/
│       └── release.yml
├── server/
│   ├── __init__.py
│   └── app.py
├── web/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── tests/
│   └── smoke.py
├── gameforge_desktop.py
├── GameForgeAI.spec
├── requirements.txt
├── requirements-build.txt
└── documentation
```

Do not confuse this with a project directory.

The core source is the application.

A `.gfai` project is user content managed by the application.

---

# 6. Entry point

`gameforge_desktop.py` is the frozen application entry point.

Its responsibilities are intentionally small:

1. inspect process arguments;
2. if the first argument ends with `.gfai`, normalize it and convert it to:
   ```text
   --project-file <absolute path>
   ```
3. forward other arguments;
4. import `server.app`;
5. run the backend main function.

Keeping this file small reduces packager-specific complexity.

---

# 7. Backend

The majority of current behavior lives in:

```text
server/app.py
```

This file currently combines:

- application path logic;
- user-data paths;
- project registry;
- `.gfai` handling;
- project indexing;
- command execution;
- project creation;
- persistent agent contract generation;
- autonomous agent loop;
- OpenCV monitor;
- upload scanning;
- process enumeration;
- managed process control;
- Git;
- input replay;
- research;
- asset analysis;
- system status;
- HTTP API;
- static frontend serving;
- process main loop.

This is convenient for an alpha but is a future refactoring candidate.

A maintainer should avoid prematurely splitting it during CI stabilization because that creates unnecessary failure surfaces.

---

# 8. Resource root vs user-data root

A frozen PyInstaller program may unpack embedded resources to a temporary `_MEIPASS` directory.

GameForge therefore distinguishes:

## Resource root

Source/web files bundled into the application.

When frozen:

```python
sys._MEIPASS
```

is used when available.

When running from source:

the repository root is used.

## User data root

Mutable application data must not be stored in the frozen resource directory.

Platform intent:

### Windows

```text
%LOCALAPPDATA%\GameForgeAI
```

### macOS

```text
~/Library/Application Support/GameForgeAI
```

### Linux

```text
$XDG_DATA_HOME/gameforgeai
```

or:

```text
~/.local/share/gameforgeai
```

This separation is critical for a one-file executable.

---

# 9. Mutable global application data

Within the user-data area GameForge currently creates:

```text
projects/
UPLOAD/
logs/
project_registry.json
```

`project_registry.json` maps a GameForge project ID to the project's actual directory.

External projects can therefore live anywhere.

---

# 10. `.gfai` manifest

The current manifest format is JSON.

Required conceptual fields:

```json
{
  "format": "GameForgeAI.Project",
  "format_version": 1,
  "project_id": "example",
  "root": ".",
  "config": "gameforge.json"
}
```

Additional fields normally include:

```json
{
  "name": "Example",
  "goal": "goal.md",
  "uploads": "UPLOAD",
  "project_index": ".gameforge/project_index.json"
}
```

## Resolution rule

`root` is resolved relative to the `.gfai` file.

This makes project directories portable when moved as a unit.

## Validation behavior

`open_gfai_file()` verifies:

- extension `.gfai`;
- manifest is an object;
- `format == "GameForgeAI.Project"`;
- `format_version == 1`;
- referenced project config exists.

Then it registers and indexes the project.

---

# 11. Project registry

`register_project_root()`:

1. resolves the real root path;
2. reads `gameforge.json`;
3. determines the project ID;
4. updates `project_registry.json`.

`project_path(project_id)` first checks the registry.

If no valid registry entry exists, it falls back to the default internal projects directory.

This design allows both:

- application-created internal projects;
- externally stored `.gfai` projects.

---

# 12. Project indexing

`scan_project_tree()` recursively inventories the project.

Current behavior:

- ignores major generated/dependency directories such as `.git`, `.venv`, `node_modules`, `__pycache__`;
- records file path;
- byte size;
- extension;
- modification time;
- stops at a configured maximum file count;
- writes `.gameforge/project_index.json`.

The index is metadata, not a replacement for semantic source search.

Large repositories may eventually need incremental indexing.

---

# 13. Default project creation

`create_project()` creates directories including:

```text
UPLOAD/MODELS
UPLOAD/TEXTURES
UPLOAD/ANIMATIONS
UPLOAD/AUDIO
UPLOAD/UI
UPLOAD/REFERENCE
UPLOAD/MODS
UPLOAD/SOURCE
UPLOAD/REPOS
UPLOAD/TOOLS
UPLOAD/DOCS
UPLOAD/ROMS_LOCAL
workspace
research
logs
captures
.gameforge
```

It writes:

```text
gameforge.json
goal.md
AGENTS.md
UPLOAD/README.txt
.gameforge/acceptance.json
*.gfai
.gameforge/project_index.json
```

If Git exists, it initializes Git and attempts an initial commit.

---

# 14. Default project configuration

Current representative shape:

```json
{
  "id": "project-id",
  "name": "Project Name",
  "created_at": "...",
  "goal": "...",
  "research_mode": "deep",
  "internet_research": true,
  "commands": {
    "build": "",
    "test": "",
    "launch": ""
  },
  "command_timeout_sec": 1800,
  "agent": {
    "permission_mode": "full-auto",
    "max_iterations": 0,
    "cooldown_sec": 3
  },
  "visual": {
    "monitor": 1,
    "interval_sec": 1.0,
    "freeze_seconds": 8,
    "black_mean_threshold": 8.0,
    "region": null,
    "window_title": ""
  },
  "log_globs": [
    "logs/**/*",
    "*.log",
    "**/*.log"
  ]
}
```

## `research_mode`

Allowed by project creation:

```text
off
normal
deep
exhaustive
```

## `max_iterations`

`0` means effectively unbounded until another stop condition occurs.

---

# 15. Persistent AGENTS contract

New projects receive `AGENTS.md`.

It is the behavioral contract for autonomous coding iterations.

It covers:

- scope;
- user intent;
- research;
- uploads;
- provenance;
- API honesty;
- reversible work;
- evidence;
- regression;
- completion;
- distribution hygiene.

If an associated project behaves incorrectly because the AI repeatedly ignores requirements, inspect `AGENTS.md` before modifying core code.

Sometimes the problem is the project contract, not GameForge.

---

# 16. Acceptance engine

`acceptance_is_complete()` currently requires:

1. `project_complete` true;
2. criteria list exists;
3. every criterion status is exactly `pass`;
4. every criterion has non-empty evidence;
5. if build is configured, build must be successful;
6. if test is configured, test must be successful.

This intentionally makes completion conservative.

A future system should validate evidence more deeply rather than trusting project JSON state alone.

---

# 17. Autonomous agent state

`AgentState` tracks:

```text
project_id
status
iteration
message
started_at
last_update
stop_event
pause_event
thread
```

Known statuses include:

```text
idle
running
paused
blocked
complete
error
stopped
```

The agent runs in a daemon thread.

If changing threading behavior, test application shutdown carefully.

---

# 18. Agent loop in detail

`agent_loop(project_id)` performs the following:

## 18.1 Load project/config

Reads the project and current settings.

## 18.2 Require Codex

If `codex` is missing from PATH:

```text
status = blocked
```

Current single-file GameForge does not embed Codex itself.

## 18.3 Pause handling

The loop remains alive while a pause event is set.

## 18.4 Iteration count

Each iteration increments state.

If `max_iterations` is non-zero and exceeded, it pauses.

## 18.5 Pre-iteration Git checkpoint

A commit is attempted before AI changes.

## 18.6 Prompt generation

`build_agent_prompt()` includes:

- iteration number;
- instruction to read project control files;
- research mode;
- internet research flag;
- requirement to implement rather than only describe;
- latest logs;
- latest visual evidence;
- previous build/test result.

## 18.7 Codex invocation

Current command begins with:

```text
codex exec --json
```

When project `permission_mode` is `full-auto`, the command adds:

```text
--full-auto
```

## 18.8 Codex output

Stdout JSONL is written to iteration logs.

Stderr/final text is also recorded.

## 18.9 Authentication/usage detection

If Codex returns failure containing common strings such as:

```text
usage limit
rate limit
sign in
login
authentication
```

the project is marked blocked.

## 18.10 Build

Runs configured build command.

## 18.11 Test

Runs configured test command.

## 18.12 Evidence

Writes `.gameforge/last_evidence.json`.

## 18.13 Completion check

If acceptance passes, GameForge creates a verified-completion checkpoint.

## 18.14 Otherwise

It checkpoints progress and continues after cooldown.

---

# 19. Command execution

`run_shell()` is used for build/test/manual commands.

When debugging project commands, distinguish:

- executable not found;
- shell quoting;
- bad working directory;
- timeout;
- build failure;
- test failure;
- environment variable problem.

Commands execute with the project root as working directory.

This is a major assumption.

---

# 20. Research action

`run_research_task()` also requires Codex.

It instructs the agent to:

- not edit gameplay code;
- research project blockers;
- write sources;
- write a synthesis.

Outputs are logged under:

```text
logs/research-<timestamp>.jsonl
```

If research appears ineffective:

1. verify Codex is installed/authenticated;
2. inspect research log;
3. inspect `research/SOURCES.md`;
4. inspect `research/LATEST_RESEARCH.md`;
5. improve project-specific question;
6. only then assume core research logic is broken.

---

# 21. Upload scanning

`scan_uploads()` recursively hashes files.

Current hash:

```text
SHA-256
```

This is useful for:

- provenance;
- duplicate detection later;
- identifying whether an upload changed;
- reproducibility.

Current upload scanning does **not** itself perform malware analysis, license inference, or conversion.

Those are future capabilities.

---

# 22. Upload API

The backend has an upload endpoint that:

- accepts category;
- accepts relative filename/path;
- caps request size at approximately 2 GB;
- confines writes under the chosen project's `UPLOAD/<category>`;
- uses safe path resolution to prevent simple path traversal.

When debugging uploads, check:

- HTTP Content-Length;
- category normalization;
- safe path check;
- filesystem permissions;
- disk space.

---

# 23. Asset analysis

`analyze_assets()` currently performs lightweight analysis.

## Images

Uses OpenCV where possible.

## OBJ

Parses line prefixes to count:

```text
v
vt
vn
f
```

## Other model formats

Classified but not deeply parsed.

This means the core should not claim to natively retopologize FBX by itself.

A project may use Blender or other tooling.

---

# 24. Visual monitor

`cv_loop()` uses:

- `mss` for capture;
- NumPy for frame arrays;
- OpenCV for grayscale/diff/output.

## Capture source

Configured monitor index by default.

On Windows, a configured `window_title` can use `pygetwindow` to determine a window rectangle.

A manual region can override capture bounds.

## Metrics

Current output includes:

```text
timestamp
monitor
region
mean_brightness
contrast_std
frame_diff_mean
black_screen_suspected
frozen_screen_suspected
```

## Black screen

Current heuristic:

- mean brightness below configured threshold;
- contrast standard deviation below 12.

## Freeze

Current heuristic:

- frame diff below 0.8;
- persists for configured freeze duration.

These values are heuristics.

Do not treat them as universal proof.

## Output

Latest frame:

```text
captures/latest.jpg
```

Metrics:

```text
captures/metrics.json
```

---

# 25. Process handling

## Process list

Uses `psutil.process_iter()`.

Provides:

- PID;
- name;
- executable;
- command line;
- create time.

## Managed process

A project can launch its configured launch command.

GameForge stores:

- command;
- start time;
- PID;
- log path;
- return code.

### Windows

Uses a new process group and `taskkill /T /F` for tree termination.

### POSIX

Uses a new session and process-group SIGTERM.

Be cautious modifying this code. Process tree semantics differ by platform.

---

# 26. Input replay

Current implementation uses `pynput`.

Supported keyboard names include common:

```text
enter
escape
space
tab
shift
ctrl
alt
backspace
delete
arrows
home
end
pageup
pagedown
F1-F12
```

Single-character keys are supported.

Mouse supports:

- left/right/middle click;
- relative movement.

The current CI may use:

```text
PYNPUT_BACKEND=dummy
```

so CI can import/test without a real graphical desktop input backend.

Do not confuse dummy CI input with real gameplay input validation.

---

# 27. Git behavior

## Checkpoint

`git_checkpoint()`:

```text
git add -A
git commit -m ...
git rev-parse HEAD
```

"nothing to commit" is accepted as non-failure.

## Status

Reports:

- `git status --short`;
- recent log;
- HEAD.

## Rollback

Only accepts revision strings matching 7–40 hex characters.

Before hard reset, it creates a safety checkpoint.

Then:

```text
git reset --hard <revision>
```

This is intentionally destructive to working-tree changes after the safety commit.

Future improvements may use worktrees/branches more extensively.

---

# 28. HTTP API

Current important GET routes:

```text
GET /api/status
GET /api/projects
GET /api/project/<id>/state
GET /api/project/<id>/index
GET /api/project/<id>/processes
GET /api/project/<id>/logs
GET /api/project/<id>/capture.jpg
```

Important POST routes:

```text
POST /api/projects/open-gfai
POST /api/projects/create

POST /api/project/<id>/config
POST /api/project/<id>/agent/start
POST /api/project/<id>/agent/pause
POST /api/project/<id>/agent/resume
POST /api/project/<id>/agent/stop

POST /api/project/<id>/cv/start
POST /api/project/<id>/cv/stop

POST /api/project/<id>/uploads/scan
POST /api/project/<id>/upload

POST /api/project/<id>/run/build
POST /api/project/<id>/run/test
POST /api/project/<id>/run/launch

POST /api/project/<id>/git/checkpoint
POST /api/project/<id>/git/status
POST /api/project/<id>/git/rollback

POST /api/project/<id>/process/start
POST /api/project/<id>/process/stop

POST /api/project/<id>/input/replay
POST /api/project/<id>/research/run
POST /api/project/<id>/assets/analyze
POST /api/project/<id>/acceptance/update
```

A future refactor should formalize schemas and API versioning.

---

# 29. Frontend

The frontend is intentionally lightweight:

```text
web/index.html
web/app.js
web/style.css
```

The Python server serves these as static embedded resources.

If a frozen executable starts but displays a blank/404 page:

1. inspect PyInstaller `datas`;
2. verify `web` is bundled;
3. verify `_resource_root()`;
4. inspect static path resolution;
5. confirm `index.html` exists under frozen resource root.

---

# 30. HTTP server

Current backend uses Python's:

```text
ThreadingHTTPServer
SimpleHTTPRequestHandler
```

This is appropriate for a local alpha control server.

It is not currently designed as a hardened public internet service.

Do not expose it directly to the public internet.

LAN behavior should eventually add stronger authentication/CSRF/security controls.

---

# 31. Main application startup

The backend main routine:

- parses host;
- parses port;
- parses no-browser;
- parses optional `.gfai` project;
- opens/registers project before serving;
- starts HTTP server;
- opens browser unless disabled.

The frontend can be focused on a project through a query parameter.

---

# 32. System status

`/api/status` currently reports:

- platform string;
- Python version;
- Git availability;
- Codex availability;
- Codex version if detectable;
- OpenCV import;
- MSS import;
- psutil import;
- hostname.

This is a quick diagnostic endpoint.

It does not prove all project-specific dependencies exist.

---

# 33. Packaging

`GameForgeAI.spec` defines PyInstaller collection.

The release goal is `onefile`.

PyInstaller packages Python, imported code, native modules, and declared resources.

## Important rule

PyInstaller builds are OS-specific.

Build Windows binary on Windows.

Build Linux binary on Linux.

Build macOS binary on macOS.

Do not claim a cross-compiled binary is validated unless explicitly supported/tested.

---

# 34. CI architecture

The GitHub workflow performs roughly:

```text
checkout
→ setup Python
→ detect source root
→ print diagnostics
→ upgrade pip tooling
→ install runtime dependencies
→ install PyInstaller
→ dependency import check
→ source smoke test
→ PyInstaller build
→ rename executable
→ launch frozen executable
→ poll /api/status
→ upload artifact
→ optional attach to GitHub Release
```

This sequencing is deliberate.

It isolates failures.

---

# 35. Current CI source-root compatibility

The workflow supports:

## Layout A

```text
repo/
requirements.txt
GameForgeAI.spec
...
```

## Layout B

```text
repo/
GameForgeAI/
    requirements.txt
    GameForgeAI.spec
```

This was added because the user's GitHub upload used a nested `GameForgeAI` directory.

---

# 36. Smoke test purpose

`tests/smoke.py` tests source-level core behavior.

It uses a temporary user-data directory and checks:

- project creation;
- `.gfai` creation/opening;
- project indexing;
- local HTTP server;
- `/api/status`;
- frontend root.

It is not a full autonomous game-development test.

---

# 37. v1.0.4 smoke import fix

When Python runs a script by path, Python's import root may be the script directory.

Therefore:

```text
tests/smoke.py
```

could not see sibling:

```text
server/
```

The test now inserts:

```python
Path(__file__).resolve().parents[1]
```

into `sys.path`.

If this bug reappears, verify the repository running in CI actually contains the patched file.

---

# 38. Dependency strategy

Runtime dependencies include core packages for:

- OpenCV;
- screen capture;
- process inspection;
- NumPy;
- input automation;
- Windows window targeting conditionally.

Build dependency:

- PyInstaller.

Python 3.12 is currently used in CI for package compatibility.

The actual frozen app contains its Python runtime.

---

# 39. Why Windows ARM64 is currently omitted

A reliable release matrix must reflect dependencies, not aspirations.

If the required OpenCV packaging path cannot provide the needed Windows ARM64 wheel/runtime combination, the target should remain unsupported until validated.

Future options:

- different OpenCV packaging;
- custom native build;
- reduced visual feature binary;
- alternate CV backend.

Do not silently publish an unverified ARM64 binary.

---

# 40. macOS one-file tradeoff

A literal raw single executable can be distributed.

But macOS Finder document association is normally integrated through an application bundle/document type.

The project currently prioritizes one-file delivery.

Therefore:

- command-line/open-with `.gfai` path is feasible;
- full Finder-native `.gfai` ownership may require an `.app` bundle.

Document this rather than pretending both constraints are simultaneously satisfied.

---

# 41. External dependencies

GameForge's binary is self-contained for GameForge's Python runtime.

It is not self-contained for every game-development universe.

Potential project dependencies include:

- game installation;
- legal ROM;
- decomp source;
- mod loader;
- game SDK;
- compiler;
- Java;
- Node;
- Blender;
- emulator;
- proprietary editor;
- asset converter;
- platform SDK.

GameForge should eventually detect and guide installation.

Right now associated project setup may still require manual/tool-agent work.

---

# 42. Codex dependency

Current autonomous work uses the `codex` executable.

If missing:

GameForge reports the agent blocked.

If unauthenticated/limited:

Codex output may cause GameForge to enter blocked status.

A future core should provide clearer interactive login/install UX.

---

# 43. Associated project vs core bug

This distinction is essential.

## Likely core GameForge bug

Examples:

- dashboard never loads for any project;
- `.gfai` parser fails valid files;
- project registry points to incorrect paths;
- upload API escapes project root;
- Git checkpoint logic breaks every project;
- OpenCV subsystem crashes before capture;
- CI cannot package the application;
- frozen app cannot find embedded frontend.

## Likely associated-project bug

Examples:

- Unreal project does not compile;
- OoT decomp expects a different ROM revision;
- Titanfall script API doesn't exist;
- Minecraft dependency version conflicts;
- game-specific model export fails;
- emulator command is wrong;
- project build command is missing.

Do not modify GameForge core just because one project's toolchain is incorrect.

---

# 44. AI repair protocol

An AI asked to repair GameForge should follow this order.

## Step 1 — identify scope

Is the failure:

```text
CORE
CI/PACKAGING
PLATFORM
DEPENDENCY
PROJECT CONFIG
PROJECT SOURCE
GAME RUNTIME
```

State which category is most likely.

## Step 2 — capture exact failure

Use the exact:

- exception;
- exit code;
- failing workflow step;
- log line;
- HTTP error;
- project command;
- platform.

Do not start by rewriting architecture.

## Step 3 — inspect authoritative files

For core:

```text
server/app.py
gameforge_desktop.py
GameForgeAI.spec
requirements.txt
requirements-build.txt
.github/workflows/release.yml
tests/smoke.py
web/*
```

For a project:

```text
*.gfai
gameforge.json
goal.md
AGENTS.md
.gameforge/acceptance.json
research/
logs/
captures/
Git history
```

## Step 4 — reproduce minimally

Prefer a targeted reproduction.

Examples:

```text
python tests/smoke.py
python -m PyInstaller ...
curl /api/status
run only build command
run only test command
open only the .gfai parser
```

## Step 5 — change minimum surface

CI YAML bug?

Change workflow only.

Smoke import bug?

Change smoke test only.

Do not ship unrelated refactors in a repair patch.

## Step 6 — test at the same layer

A YAML change must be YAML-parsed.

A Python change must syntax-check.

A source runtime change should run smoke tests.

A frozen-app change must test frozen app.

A platform-specific bug must be tested on that platform.

## Step 7 — regression test

Verify the fix did not break:

- other source layouts;
- other platforms;
- `.gfai`;
- project creation;
- API;
- frontend.

## Step 8 — document

Update:

```text
CHANGELOG.md
STAGED_UPDATE_PLANNER.md
```

when milestone status actually changes.

---

# 45. Patch-delivery convention

The user currently prefers delta-only update ZIPs.

A patch ZIP should contain only:

- changed files;
- added files.

Its top-level directory must be:

```text
GameForgeAI/
```

If files need to be removed, list them explicitly in the response rather than putting unrelated files in the patch.

This convention should be preserved in future support responses unless the user asks for a full repo.

---

# 46. Project-specific AI repair protocol

When a `.gfai` project fails:

## Read first

```text
goal.md
AGENTS.md
gameforge.json
.gameforge/acceptance.json
```

## Inspect

```text
.git
research/
UPLOAD/
logs/
captures/
.gameforge/last_evidence.json
.gameforge/iteration_notes.md
```

## Verify configured commands

```json
commands.build
commands.test
commands.launch
```

Blank commands mean GameForge has nothing project-specific to execute yet.

That may be expected early in toolchain discovery.

## Determine baseline

Before changing a mod/decomp/game project:

- verify the original/baseline works;
- record version;
- record toolchain;
- record known-good Git revision.

## Preserve original files

Especially:

- user uploads;
- commercial base games;
- ROMs;
- reference assets.

---

# 47. Project classes GameForge is intended to support

## From-nothing game creation

Prompt → choose feasible engine/toolchain → scaffold → build → run → test.

## Campaign continuation

Use a modding/source path to create new missions while preserving previous campaign behavior.

## Game fusion

Decompose "merge these games" into implementable mechanics rather than pretending binaries can be fused.

## Decomp/ROM transformation

Use public decomp/homebrew/recomp projects and local legal base content.

## Existing game mod

Use public/authorized tooling.

## Engine project

Unity/Unreal/Godot/etc.

## Modded sandbox/game ecosystem

Minecraft-style Java/mod-loader projects.

---

# 48. Example: campaign continuation

A strong campaign continuation project should define:

- base game version;
- modding framework;
- mission list;
- technical vertical slice;
- story/canon research;
- mission acceptance criteria;
- per-mission regression suite;
- final campaign progression test.

GameForge should not try to create ten missions before proving one mission loads and completes.

---

# 49. Example: game fusion

"Put game A into game B" should become a systems map.

For example:

```text
player controller
camera
interaction
world representation
inventory
hotbar
crafting
persistence
physics
AI
UI
audio
vehicle interaction
```

Each system needs:

- target-engine implementation;
- acceptance test;
- performance budget;
- regression boundary.

---

# 50. Example: decomp/ROM FPS transformation

A proper workflow should be:

```text
legal base input
→ clean source build
→ known-good ROM hash
→ target scene identification
→ pickup proof
→ asset conversion
→ build
→ emulator boot
→ collect
→ equip
→ fire
→ damage
→ UI/ammo
→ save/load
→ regression
→ distribution-safe patch/build instructions
```

The modern source asset should be adapted to target hardware/art constraints.

---

# 51. Security concerns

GameForge controls build commands and can launch external processes.

That means a project can be dangerous.

Current alpha should not be treated as a hardened sandbox.

Future trust controls are required.

Do not open/run untrusted project scripts casually.

Potential risks:

- malicious build script;
- destructive shell command;
- credential access;
- network download/execute;
- path traversal in project tooling;
- malicious source repository.

The core upload endpoint itself uses safe path resolution, but that does not sandbox project build commands.

---

# 52. Safe-path behavior

`safe_child(root, rel)` resolves a path and checks it remains under the specified root.

This is used for several application-controlled file paths.

When modifying filesystem code, retain path containment.

Do not replace safe resolution with naive string concatenation.

---

# 53. Large files

Upload API accepts very large input by design for game assets.

Current JSON body size is capped much smaller.

Game projects may involve multi-gigabyte content.

Avoid reading arbitrary large project files fully into memory.

---

# 54. Generated/runtime files

Do not treat these as core source:

```text
logs/
captures/
.gameforge/last_evidence.json
.gameforge/upload_manifest.json
.gameforge/asset_analysis.json
.gameforge/project_index.json
Codex iteration logs
```

They are runtime state/evidence.

---

# 55. Source of truth hierarchy

When debugging contradictions:

1. actual code;
2. current project config/state;
3. current runtime logs;
4. CI log;
5. this documentation;
6. old chat summaries/prototype behavior.

Documentation should be updated when code intentionally changes.

---

# 56. Error taxonomy

Use these labels in issue reports.

## CORE-STARTUP

Executable/server cannot start.

## CORE-WEB

Frontend cannot load or API/static path broken.

## CORE-PROJECT

`.gfai`, registry, project indexing, project create.

## CORE-AGENT

Codex loop behavior.

## CORE-CV

Visual capture/analysis.

## CORE-PROCESS

Launch/stop/list process.

## CORE-INPUT

Keyboard/mouse/controller automation.

## CORE-GIT

Checkpoint/status/rollback.

## CORE-UPLOAD

Upload/scanning/provenance.

## CORE-ASSET

Core metadata analysis.

## CI-YAML

Workflow syntax/expression.

## CI-DEPS

Dependency install/import.

## CI-PACKAGE

PyInstaller build.

## CI-FROZEN

Frozen app launches incorrectly.

## PLATFORM

OS/architecture-specific issue.

## PROJECT-TOOLCHAIN

Compiler/SDK/mod loader/decomp setup.

## PROJECT-CODE

Game-specific code failure.

## PROJECT-RUNTIME

Game/emulator behavior.

This taxonomy helps avoid random changes.

---

# 57. Recommended issue template content

Every bug report should contain:

```text
GameForge version / commit
OS
architecture
source or frozen binary
project type
exact action
expected result
actual result
exact error
reproduction steps
logs
whether issue happens in an empty/smoke project
```

For CI:

```text
job name
runner label
step name
first failing command
full relevant traceback/output
```

---

# 58. Release criteria

A source revision should not be called a stable release until:

- all supported native CI jobs pass;
- source smoke passes;
- frozen smoke passes;
- frontend embedded load passes;
- `.gfai` open passes;
- new project creation passes;
- basic Git handling passes when Git available;
- application does not write mutable project state into frozen resources;
- no known data-loss bug;
- current limitations documented.

---

# 59. What "single-file" actually means

Single-file means the **GameForge application distribution** is one executable.

When it starts, PyInstaller may extract runtime components to a temporary directory as part of one-file execution.

That is normal.

It does not mean:

- every compiler is inside it;
- every game SDK is inside it;
- every emulator is inside it;
- every commercial game is inside it.

Those would be technically enormous, often platform-specific, and often legally impossible.

---

# 60. Future refactoring boundaries

Once CI/release is stable, `server/app.py` could sensibly split into:

```text
core/paths.py
core/projects.py
core/gfai.py
core/agent.py
core/research.py
core/git.py
core/processes.py
core/input.py
core/vision.py
core/assets.py
core/api.py
```

Do not do this merely for cleanliness while packaging is still failing.

Stabilize first.

---

# 61. Current known limitations

At v1.0.4 documentation state:

- native build matrix still awaits full green verification after latest fixes;
- semantic game-state visual detectors are not core yet;
- controller input is not core yet;
- source URL auto-fetch is not part of this minimal v1.0 single-file core;
- deep 3D model inspection is limited;
- automatic external toolchain installation is not part of final one-file core yet;
- Codex remains external;
- Git remains external;
- project build toolchains remain external;
- no hardened untrusted-project sandbox;
- macOS raw one-file executable conflicts with full native Finder document association;
- Windows ARM64 full feature build is not currently supported;
- acceptance evidence is human/agent populated rather than cryptographically/semantically verified by core.

These are product gaps, not reasons to hide current capabilities.

---

# 62. How an AI should improve this project

Prefer this priority order:

1. make current release pipeline green;
2. make failures diagnosable;
3. protect data;
4. harden project lifecycle;
5. improve dependency/toolchain detection;
6. improve automated game observation;
7. improve automated input;
8. improve asset pipelines;
9. add engine adapters;
10. add broader features.

Avoid adding flashy features while basic native packaging is red.

---

# 63. How an AI should not improve this project

Do not:

- rewrite everything into another framework because of one bug;
- remove regression safeguards;
- remove evidence requirements;
- hardcode one user's project into the core application;
- embed pirated game content;
- silently run arbitrary downloaded executables;
- call unsupported platforms supported;
- create placeholder APIs and claim implementation;
- mark acceptance complete without evidence;
- make project-root path assumptions without testing nested/root layouts;
- package loose source files in a binary-only release.

---

# 64. Associated project compatibility philosophy

GameForge should be general, while projects should be specific.

Core knows how to:

- orchestrate;
- capture;
- checkpoint;
- run;
- observe;
- iterate.

Project adapters/templates know:

- engine;
- compiler;
- game API;
- asset pipeline;
- launch flags;
- logs;
- success states.

This boundary should remain clear.

---

# 65. Final mental model

Think of GameForge as a local automated game-development lab.

It contains:

```text
PROJECT MANAGER
+
AI DEVELOPMENT ORCHESTRATOR
+
BUILD/TEST RUNNER
+
PROCESS SUPERVISOR
+
VISUAL SMOKE TESTER
+
INPUT DRIVER
+
GIT SAFETY SYSTEM
+
ACCEPTANCE ENGINE
+
WEB CONTROL PANEL
```

It is not one giant game engine.

It coordinates the tools and source appropriate to each project.

The target end state is that a human can describe a playable result, provide whatever legal/proprietary inputs are necessary, and GameForge can repeatedly do the engineering work required to move that project toward verified completion.

That is the architectural intent future maintainers and AI agents should preserve.
