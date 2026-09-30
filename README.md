# GameForge AI

**Current documented development state: v1.0.4 — CI / native single-file release stabilization**

GameForge AI is a desktop-oriented autonomous game-development control system. Its purpose is to accept a game-development goal, attach that goal to a portable project, let an AI coding agent work inside that project, repeatedly build/test/launch the result, collect evidence from logs and the running game, protect known-good work with Git, and continue iterating until explicit acceptance criteria are satisfied or a real blocker is documented.

GameForge is not intended to be a general-purpose AI desktop assistant. Its scope is game creation, game editing, modding, decomp/ROM work, campaign/mission creation, game-system fusion, asset adaptation, gameplay debugging, automated playtesting, performance validation, regression protection, and packaging.

---

## Current status

GameForge's **core source architecture exists** and the current focus is getting the native one-file release pipeline green on every supported CI target.

### Current milestone

**v1.0.4: smoke-test import-path repair**

The most recent issue fixed was:

```text
ModuleNotFoundError: No module named 'server'
```

when CI executed:

```text
python tests/smoke.py
```

from the test script's directory context. `tests/smoke.py` now inserts the project root into `sys.path` before importing the backend.

### Current release targets

The active single-file build matrix is intended to produce:

```text
GameForgeAI-Windows-x64.exe
GameForgeAI-Linux-x64
GameForgeAI-Linux-arm64
GameForgeAI-macOS-x64
GameForgeAI-macOS-arm64
```

Windows ARM64 is not currently considered a supported full-feature release target because the current OpenCV Python packaging path does not provide the same reliable Windows ARM64 wheel path as the supported targets.

**Important:** the build matrix is still being stabilized. A platform is not considered release-verified merely because its source is expected to work. The corresponding native CI job must successfully build the one-file executable and pass the frozen-executable smoke test.

---

# What GameForge does

At a high level:

```text
USER GOAL
    ↓
.gFAI PROJECT
    ↓
PROJECT INDEX + CONFIG + ACCEPTANCE CONTRACT
    ↓
RESEARCH / SOURCE INSPECTION / UPLOAD ANALYSIS
    ↓
AI IMPLEMENTATION ITERATION
    ↓
GIT CHECKPOINT
    ↓
BUILD
    ↓
TEST
    ↓
LAUNCH / MANAGE GAME OR TOOL
    ↓
LOG + PROCESS + VISUAL EVIDENCE
    ↓
ACCEPTANCE / REGRESSION EVALUATION
    ↓
FIX OR CONTINUE
    ↓
REPEAT UNTIL COMPLETE OR GENUINELY BLOCKED
```

GameForge is deliberately designed so that **"it compiled" does not equal "done."**

A project is only complete when its `.gameforge/acceptance.json` is explicitly marked complete and every criterion has evidence.

---

# Core concepts

## 1. `.gfai` project files

A `.gfai` file is the portable entry point into a GameForge project.

Typical example:

```json
{
  "format": "GameForgeAI.Project",
  "format_version": 1,
  "project_id": "oot-fps-ar15",
  "name": "OoT FPS AR15",
  "root": ".",
  "config": "gameforge.json",
  "goal": "goal.md",
  "uploads": "UPLOAD",
  "project_index": ".gameforge/project_index.json"
}
```

The project itself is a normal directory and can live outside the GameForge installation.

Opening a `.gfai` file causes GameForge to:

1. validate the manifest;
2. resolve the project root relative to the `.gfai` file;
3. locate `gameforge.json`;
4. register the project in the user's GameForge project registry;
5. scan/index the project tree;
6. open the dashboard for that project.

---

## 2. Project folder

A normal project can contain:

```text
MyProject/
├── MyProject.gfai
├── gameforge.json
├── goal.md
├── AGENTS.md
├── UPLOAD/
├── research/
├── workspace/
├── logs/
├── captures/
├── source/game-specific files
└── .gameforge/
```

Projects do not need to be stored inside the application directory.

---

## 3. `gameforge.json`

This is the primary machine-readable project configuration.

It currently controls:

- project identity;
- research mode;
- whether internet research is requested;
- build/test/launch commands;
- command timeout;
- autonomous agent settings;
- OpenCV capture settings;
- log glob patterns.

The application reloads this file during autonomous runs, allowing a project or AI agent to discover and update commands as the real toolchain is established.

---

## 4. `goal.md`

This is the durable human-readable project objective.

Examples include:

- create a new game;
- continue a campaign;
- add new missions;
- turn a decomp project into an FPS;
- adapt an uploaded weapon model;
- recreate one game's gameplay systems in another engine;
- diagnose and repair a broken modded game project.

The AI is expected to preserve the user's goal across iterations.

---

## 5. `AGENTS.md`

This is the persistent development contract given to AI coding agents.

It tells them to:

- stay inside game-development scope;
- research instead of inventing APIs;
- inspect uploads;
- preserve provenance;
- work incrementally;
- use Git;
- collect runtime evidence;
- protect regression behavior;
- avoid false completion claims;
- maintain acceptance criteria;
- document real blockers.

This file is one of the most important project-level control documents.

---

## 6. `.gameforge/acceptance.json`

This is GameForge's definition-of-done contract.

Example:

```json
{
  "project_complete": false,
  "criteria": [
    {
      "id": "playable",
      "description": "A playable build matching the user's goal exists",
      "status": "pending",
      "evidence": ""
    }
  ]
}
```

A GameForge project should not be marked complete until:

- `project_complete` is true;
- every criterion is `pass`;
- every criterion has non-empty evidence;
- configured build/test commands still pass.

---

# Autonomous development loop

The current autonomous loop is implemented in `server/app.py`.

Each iteration:

1. reloads project state;
2. creates a Git checkpoint;
3. builds an iteration prompt;
4. launches Codex CLI using `codex exec --json`;
5. asks Codex to inspect the project, goal, uploads, research, acceptance state, source, and Git history;
6. asks it to make safe reversible progress;
7. captures Codex logs;
8. reloads project configuration;
9. runs the configured build command;
10. runs the configured test command;
11. records evidence;
12. evaluates acceptance;
13. commits progress;
14. repeats.

The loop can pause for:

- user pause;
- user stop;
- authentication/usage problems;
- configured iteration limits;
- unhandled errors;
- successful completion.

---

# Evidence systems

GameForge currently understands several forms of evidence.

## Build and test output

Commands configured under:

```json
"commands": {
  "build": "...",
  "test": "...",
  "launch": "..."
}
```

run with captured output and log files.

## Runtime logs

Project-specific log globs can collect:

```text
logs/**/*
*.log
**/*.log
```

The agent can use this evidence during later iterations.

## Visual evidence

The OpenCV/MSS monitor currently performs generic smoke checks:

- frame capture;
- mean brightness;
- contrast;
- frame-to-frame difference;
- suspected black screen;
- suspected frozen screen.

The current visual system is intentionally generic. Project-specific semantic detectors are a planned expansion.

## Process evidence

GameForge can:

- list processes;
- launch a project-managed process;
- track PID;
- write launch logs;
- stop the managed process tree.

## Input replay

Current input replay supports:

- key press;
- key down;
- key up;
- mouse click;
- relative mouse movement;
- sleep/delay.

Input sequences are limited to 500 steps per request.

---

# Upload intake

GameForge projects contain categorized upload folders such as:

```text
UPLOAD/
├── MODELS/
├── TEXTURES/
├── ANIMATIONS/
├── AUDIO/
├── UI/
├── REFERENCE/
├── MODS/
├── SOURCE/
├── REPOS/
├── TOOLS/
├── DOCS/
└── ROMS_LOCAL/
```

The upload scanner records:

- relative path;
- category;
- byte size;
- SHA-256;
- extension;
- whether a file appears to be a license file.

Original uploads should be treated as inputs and not destructively edited.

---

# Asset analysis

The current analyzer recognizes common model/image extensions.

Images can report:

- width;
- height;
- channel count.

OBJ files can report:

- vertices;
- faces;
- UV count;
- normal count.

Other model formats are currently classified as models but are not yet deeply parsed by the core analyzer.

Full asset adaptation is expected to be performed by project tooling/AI agents using appropriate converters, Blender or game-specific pipelines where available.

---

# Research

GameForge has a dedicated research action that invokes Codex with instructions to:

- inspect the project;
- research only public/authorized sources;
- prefer official/primary material;
- use public source repositories;
- use archived developer material;
- use interviews and issue trackers;
- use modding documentation;
- use public reverse-engineering research;
- separate verified facts from speculation;
- record useful sources in `research/SOURCES.md`;
- write actionable synthesis to `research/LATEST_RESEARCH.md`.

---

# Git protection

Git is a core safety mechanism.

GameForge can:

- inspect status;
- inspect recent history;
- checkpoint all project changes;
- create pre-iteration commits;
- create progress commits;
- create completion commits;
- create a safety checkpoint before rollback;
- hard reset to a validated commit hash.

The purpose is to make aggressive autonomous development reversible.

---

# Single-file release architecture

The desired end-user release contains **one native executable per platform**.

The executable is built with PyInstaller and embeds:

- the Python interpreter;
- GameForge Python backend;
- web frontend;
- OpenCV and supporting Python runtime dependencies.

The executable does **not** magically include every possible external game-development dependency.

Projects may still require:

- Git;
- Codex CLI and authentication;
- compilers;
- game SDKs;
- decomp toolchains;
- Java;
- Node;
- CMake/Ninja;
- Blender;
- emulators;
- platform SDKs;
- proprietary game installations;
- mod loaders.

GameForge's responsibility is to orchestrate them when available and ultimately improve dependency detection/setup.

---

# Repository structure

The minimal single-file source repository should resemble:

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
├── README.md
├── CHANGELOG.md
├── UPCOMING.md
├── STAGED_UPDATE_PLANNER.md
└── ABOUT.md
```

---

# For users

## Opening GameForge normally

Run the native executable.

GameForge starts a local HTTP server and opens its dashboard.

## Opening a project

Pass a `.gfai` path:

```text
GameForgeAI MyProject.gfai
```

or use OS-level association where available.

## Important macOS note

A raw one-file Mach-O executable can receive a `.gfai` path, but native Finder document registration normally requires an `.app` bundle. The current release goal prioritizes a literal one-file executable.

---

# For developers

Before changing code:

1. read `ABOUT.md`;
2. read `CHANGELOG.md`;
3. read `STAGED_UPDATE_PLANNER.md`;
4. reproduce the failing behavior;
5. determine whether the failure is core, CI, dependency, or project-specific;
6. change the smallest possible surface;
7. run source smoke tests;
8. build on the actual target OS;
9. run the frozen executable smoke test;
10. update documentation and changelog.

Do not call a cross-platform release fixed until the native target job is green.

---

# Project philosophy

GameForge follows several hard rules:

- Do not fake successful game behavior.
- Do not treat compilation as completion.
- Do not invent game APIs.
- Do not silently destroy uploads.
- Do not allow later milestones to break earlier accepted milestones.
- Prefer small reversible steps.
- Preserve the last known-good state.
- Verify with the game/runtime whenever possible.
- Separate verified research from speculation.
- Record real blockers instead of hiding them.
- Keep commercial base games/ROMs local unless redistribution rights exist.

For detailed internals and repair instructions, read **ABOUT.md**.
