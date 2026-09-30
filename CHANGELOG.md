# GameForge AI Changelog

This changelog records the evolution of the GameForge concept and implementation through the current v1.0.4 stabilization point.

Versions prior to the current public GitHub source were iterative prototypes. They are included here because they explain why the current architecture exists.

---

## v1.0.4 — CI smoke-test import repair — CURRENT

### Fixed

GitHub Actions reached the source smoke test but failed with:

```text
ModuleNotFoundError: No module named 'server'
```

Cause:

```text
python tests/smoke.py
```

sets the first Python import path entry to the `tests/` directory. The sibling `server/` package therefore was not guaranteed to be importable.

### Change

`tests/smoke.py` now:

1. calculates the repository/project root from `__file__`;
2. inserts that directory into `sys.path`;
3. imports `server.app`.

### Validation

The patched test was executed from inside the test directory to reproduce the problematic import context and returned:

```text
SMOKE_OK
```

### Release status

Native one-file CI still needs to complete successfully on every supported target before v1.0 is release-verified.

---

## v1.0.3 — repository root auto-detection

### Problem

The workflow originally assumed:

```text
repository root/
requirements.txt
GameForgeAI.spec
```

but the uploaded GitHub layout had:

```text
repository root/
GameForgeAI/
    requirements.txt
    GameForgeAI.spec
```

CI failed with:

```text
ERROR: Could not open requirements file: requirements.txt
```

### Fixed

The workflow now detects either:

```text
$GITHUB_WORKSPACE/requirements.txt
```

or:

```text
$GITHUB_WORKSPACE/GameForgeAI/requirements.txt
```

and stores the resolved source directory in:

```text
GAMEFORGE_ROOT
```

All relevant build/test commands `cd` into that directory.

### Added diagnostics

When source-root detection fails, the workflow prints repository contents before stopping.

---

## v1.0.2 — workflow YAML duplicate-key repair

### Problem

The frozen executable smoke-test step contained two `env:` mappings.

GitHub rejected the workflow before execution with:

```text
Invalid workflow file
'env' is already defined
```

### Fixed

Merged:

```yaml
PYNPUT_BACKEND: dummy
ARTIFACT: ${{ matrix.artifact }}
```

into a single `env:` block.

### Validation

Workflow YAML was parsed successfully before packaging.

---

## v1.0.1 — CI dependency hardening

### Changes

- moved build target to Python 3.12 for broad package/wheel compatibility;
- pinned PyInstaller;
- replaced PyAutoGUI input implementation with `pynput`;
- split runtime/build dependency installation into separate CI steps;
- added dependency import checks;
- improved build diagnostics;
- improved frozen-executable failure output;
- moved Actions usage toward Node-24-generation GitHub Actions;
- removed Windows ARM64 from the supported full-feature matrix for the current dependency set.

### Why

The first cross-platform matrix failed across every target at a common early stage. The build needed more deterministic dependency diagnostics rather than one opaque install command.

---

## v1.0 Single-File Release Architecture

### Goal

Reduce the public release to exactly one native GameForge binary per supported platform.

### Removed from end-user release concept

- setup scripts;
- `.deb` package as primary distribution;
- unpackaged Python source;
- loose frontend files;
- loose dependencies;
- example projects;
- old launchers.

### Added

PyInstaller one-file source structure.

### Planned release files

```text
GameForgeAI-Windows-x64.exe
GameForgeAI-Linux-x64
GameForgeAI-Linux-arm64
GameForgeAI-macOS-x64
GameForgeAI-macOS-arm64
```

### Architecture

The executable contains the Python runtime, backend, web UI, and Python dependencies.

External game-development toolchains remain external by necessity.

---

## v1.0 Desktop Project System

### Major feature

Introduced portable `.gfai` project entry files.

### Added

- external project registry;
- project roots allowed anywhere on disk;
- relative-path `.gfai` manifests;
- project indexing;
- `.gfai` open support;
- desktop application packaging designs;
- Windows file association script;
- Linux MIME/desktop packaging;
- macOS document-type planning;
- GitHub native build matrix.

### `.gfai` behavior

Opening a project:

1. validates manifest;
2. resolves root;
3. verifies `gameforge.json`;
4. registers project;
5. indexes project files;
6. opens dashboard focused on that project.

---

## v1.0 Alpha FastTrack

### Purpose

Move from infrastructure prototype toward the first integrated autonomous game-development runtime.

### Major systems

- project creation;
- persistent goal;
- acceptance criteria;
- Codex-driven iteration;
- Git checkpoints;
- build/test hooks;
- process management;
- log collection;
- OpenCV smoke monitoring;
- keyboard/mouse replay;
- asset analysis;
- research task;
- regression-oriented project contract.

### Important limitation

Project-specific semantic visual detection was not yet implemented. The visual layer remained a generic black-screen/freeze detector.

---

## v0.4.1 — Windows bootstrap parser fix

### Problem

The complex `.cmd` bootstrap failed on Windows with:

```text
\Windows was unexpected at this time.
```

### Cause

Fragile CMD block parsing and `%PATH%` / environment expansion behavior.

### Change

Reduced `GAMEFORGE.cmd` to a tiny launcher and moved environment detection/install logic into PowerShell.

### Result

The user successfully reached:

```text
[GameForge] Environment is ready.
[GameForge] Starting dashboard...
```

This confirmed the one-launch bootstrap concept worked on the user's Windows system.

---

## v0.4 — unified one-launch bootstrap

### Added

- Windows/macOS/Linux launchers;
- Python detection/install logic;
- Git detection/install;
- Node/npm detection/install;
- Codex CLI detection/install;
- Python virtual environment setup;
- requirements installation;
- dashboard start;
- LAN mode;
- repair/doctor/setup flags.

### Goal

A user should run one launcher rather than manually configure a development stack.

---

## v0.3 — runnable web MVP

### First functional local application concept

Included:

- local web dashboard;
- project creation;
- `UPLOAD` intake;
- Codex integration;
- autonomous iteration concept;
- Git checkpoints;
- build/test hooks;
- logging;
- generic OpenCV screen monitoring.

This was not yet a complete autonomous game studio, but it established the main runtime shape.

---

## v0.2 — generic game-development studio architecture

Expanded beyond a single Titanfall use case.

### Added conceptual modes

- FROM NOTHING;
- UPLOAD;
- GAME FUSION;
- general project profiles;
- reusable orchestration rules.

### Design shift

GameForge became a general game-development system instead of a single-project agent workspace.

---

## v0.1 — Protocol 4 starter

The earliest workspace targeted the Titanfall 2 campaign-continuation concept.

### Important ideas introduced

- persistent `AGENTS.md` contract;
- never invent game-engine APIs;
- research before implementation;
- Git safety rules;
- campaign bible;
- Northstar/public tooling research;
- playable mission acceptance expectations.

Many of those principles later became global GameForge rules.

---

# Changelog rules for future maintainers

Every non-trivial release should record:

- user-visible changes;
- architecture changes;
- dependency changes;
- project format changes;
- CI changes;
- migration requirements;
- removed features;
- known regressions;
- validation performed;
- release target status.

A CI patch should name the exact failure signature it fixes.

A feature must not be described as working on a platform unless a native test supports that statement.
