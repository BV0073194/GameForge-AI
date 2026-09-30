# GameForge AI — Upcoming Work

This file is the forward-looking engineering backlog.

It is intentionally separated from `STAGED_UPDATE_PLANNER.md`:

- `UPCOMING.md` explains **what we want to add and why**.
- `STAGED_UPDATE_PLANNER.md` explains **the ordered release stages and current position**.

---

# Highest priority: finish v1.0 release stabilization

Before adding major new features, the current one-file release pipeline must be green.

Required:

- Windows x64 native build passes;
- Linux x64 native build passes;
- Linux ARM64 native build passes;
- macOS Intel native build passes;
- macOS ARM64 native build passes;
- every built executable starts;
- `/api/status` responds;
- embedded web UI loads;
- `.gfai` project opens;
- no source/runtime files are required beside the binary.

Until these pass, v1.0 remains an alpha/stabilization build.

---

# Near-term engineering backlog

## A. CI/release hardening

Planned:

- add explicit YAML linting;
- add Python static syntax validation;
- validate `GameForgeAI.spec`;
- verify embedded web resources exist after freezing;
- add release checksums;
- emit build metadata/version into binaries;
- record commit SHA inside system status;
- add reproducible build notes;
- add artifact size guardrails;
- add startup timeout diagnostics;
- add crash output capture for frozen app tests;
- verify executable architecture matches runner architecture.

---

## B. Native application lifecycle

Planned:

- detect existing GameForge instance;
- avoid accidental duplicate local servers;
- choose a free port if default port is occupied;
- communicate selected port to frontend;
- graceful shutdown endpoint;
- save clean runtime state;
- improve browser-open reliability;
- optionally provide system tray behavior;
- local-only security/token if LAN mode is used.

---

## C. `.gfai` project workflow v2

Planned:

- formal JSON Schema validation;
- migration/version handling;
- recent-project history;
- missing-project recovery;
- moved-project relinking;
- project icon/metadata;
- project template identifier;
- optional engine/project-type metadata;
- optional dependency declarations;
- optional preferred source URLs;
- optional local-tool declarations;
- per-project compatibility constraints;
- project export/import tooling.

---

## D. Toolchain discovery and provisioning

GameForge should eventually inspect the project and determine required tooling such as:

- Git;
- Codex;
- C/C++ compilers;
- CMake;
- Ninja;
- Make;
- MSVC Build Tools;
- Clang;
- GCC;
- Python;
- Node;
- Java;
- Gradle;
- .NET;
- Blender;
- emulator(s);
- mod loader;
- game SDK;
- project-specific converters.

It should distinguish:

1. bundled;
2. installed;
3. missing but installable;
4. missing and user-authorized install required;
5. licensed/proprietary;
6. unsupported on current host.

---

## E. Better Codex integration

Planned:

- Codex availability state;
- authenticated/not-authenticated status;
- clearer usage-limit state;
- structured iteration output parsing;
- explicit changed-file extraction;
- retry policy;
- iteration budget controls;
- branch/worktree execution modes;
- multiple specialized agents:
  - research;
  - implementation;
  - build/debug;
  - QA;
  - asset;
  - release.

---

## F. Research engine

Current research uses Codex as the research worker.

Future additions:

- persistent source catalog;
- preferred source URLs;
- provenance classification;
- claim/evidence map;
- source freshness;
- primary vs secondary source labeling;
- contradictory-source tracking;
- archived-link support;
- project-specific research cache;
- research-before-code gates for unfamiliar APIs.

Desired classifications:

```text
VERIFIED PRIMARY
VERIFIED SECONDARY
DEVELOPER STATEMENT
REPORTED INFORMATION
CUT / ABANDONED CONCEPT
COMMUNITY THEORY
UNVERIFIED
PROJECT-ORIGINAL
```

---

## G. Semantic visual QA

Current CV is generic.

Future vision should support generated/project-specific detectors for:

- title/menu detection;
- loading screen;
- player spawn;
- HUD;
- health/ammo;
- objective text;
- mission complete;
- death screen;
- pause menu;
- crash dialog;
- corrupted render;
- missing texture;
- expected actor/object;
- FPS overlay;
- visual regression comparison.

The system should attach screenshot evidence to acceptance criteria.

---

## H. Input automation v2

Planned:

- absolute mouse movement;
- controller/gamepad support;
- virtual Xbox-compatible controller where supported;
- input recording;
- input macro editor;
- conditional input scripts;
- wait-until-screen-state;
- reusable test sequences;
- timeout/retry;
- focus verification;
- safe key release on abort.

---

## I. Runtime telemetry

Planned:

- CPU;
- RAM;
- GPU where available;
- VRAM;
- FPS;
- frametime;
- process responsiveness;
- crash exit codes;
- window state;
- disk usage;
- build time;
- test time;
- regression trend.

---

## J. Crash analysis

Planned:

- detect crash dumps;
- Windows Event/error retrieval where appropriate;
- parse common engine crash logs;
- symbolize dumps when symbols/toolchain exist;
- correlate crash timestamp with latest commit and input sequence;
- auto-bisect repeatable regressions where feasible.

---

## K. Project-specific engine adapters

A generic orchestrator cannot know every engine deeply.

Adapters should provide conventions for:

### Unity
- project discovery;
- batch mode;
- logs;
- test runner;
- build output;
- scenes/assets;
- editor version;
- package manifest.

### Unreal
- `.uproject`;
- UBT/UAT;
- editor command line;
- logs;
- automation tests;
- cooked builds.

### Godot
- `project.godot`;
- headless import/build;
- test/play launch;
- logs.

### Minecraft
- Gradle;
- Forge/NeoForge/Fabric;
- runClient;
- game logs;
- crash reports;
- mod compatibility.

### Source/Titanfall-style modding
- installation discovery;
- public mod loader/toolchain;
- script/map conventions;
- logs;
- runtime deployment;
- single-player capability verification.

### Decomp/ROM
- legal local base input;
- source revision;
- exact toolchain;
- clean baseline hash;
- ROM build;
- emulator launch;
- deterministic test save/state where lawful/appropriate.

---

## L. Asset pipeline

Future core should understand:

- FBX;
- OBJ;
- glTF/GLB;
- Blender;
- common texture formats;
- animation metadata;
- skeletons;
- materials;
- collision.

Planned actions:

- inspect mesh topology;
- count triangles/materials;
- detect scale;
- generate LODs;
- decimate;
- retopologize;
- bake normals;
- atlas materials;
- resize/reformat textures;
- palette reduction;
- rig conversion;
- animation retarget;
- collision generation;
- project-specific exporter.

All derivatives must retain provenance back to the original upload.

---

## M. Acceptance and regression system v2

Planned:

- machine-executable acceptance tests;
- evidence attachment;
- requirement dependency graph;
- "blocked" state with reason;
- regression suite generation;
- milestone gates;
- acceptance history;
- known-good release tag;
- automatic rollback threshold.

---

## N. Security/trust model

Opening a project can expose build scripts and third-party tools.

Future system should include:

- trust-on-first-open;
- project capability declaration;
- executable/script approval;
- path scope;
- network permission;
- external-process permission;
- protected directories;
- quarantined downloads;
- checksum/provenance display;
- never automatically execute newly downloaded binary without approval.

---

## O. Project template ecosystem

Planned official templates:

- campaign continuation;
- game fusion;
- decomp/ROM transformation;
- Unity game;
- Unreal game;
- Godot game;
- Minecraft mod;
- Source-family mod;
- emulator-driven QA project.

Templates should be separate from the core executable repository.

---

# Long-term direction

The long-term vision is not "AI writes some code."

It is:

```text
PROMPT
  ↓
FEASIBILITY
  ↓
RESEARCH
  ↓
TOOLCHAIN
  ↓
PROJECT PLAN
  ↓
IMPLEMENTATION
  ↓
BUILD
  ↓
REAL GAME
  ↓
AUTOMATED PLAYTEST
  ↓
EVIDENCE
  ↓
REPAIR
  ↓
REGRESSION
  ↓
REPEAT
  ↓
PLAYABLE RELEASE
```

The core measure of success is observable game behavior, not textual confidence.
