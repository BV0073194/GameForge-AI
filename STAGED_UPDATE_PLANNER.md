# GameForge AI — Staged Update Planner

This is the ordered development plan for GameForge AI.

Legend:

```text
✅ Complete enough to build upon
🟨 Implemented but still being stabilized / verified
⬜ Planned
⛔ Blocked by external technical constraint
```

---

# CURRENT POSITION

## 🟨 Stage 4 — Native Single-File CI Stabilization

**Current code/documentation marker: v1.0.4**

We are currently here:

```text
Stage 0  Concept / project contract                  ✅
Stage 1  Runnable local web MVP                     ✅
Stage 2  One-launch bootstrap                       ✅
Stage 3  Desktop + .gfai project architecture       ✅
Stage 4  Native one-file CI stabilization           🟨  ← CURRENT
Stage 5  Release verification / v1.0 alpha binary   ⬜
Stage 6  Core runtime hardening                     ⬜
Stage 7  Toolchain auto-discovery                   ⬜
Stage 8  Autonomous QA expansion                    ⬜
Stage 9  Asset transformation pipeline              ⬜
Stage 10 Engine/project adapters                    ⬜
Stage 11 Security/trust model                       ⬜
Stage 12 v1.0 Release Candidate                     ⬜
Stage 13 v1.0 Stable                                ⬜
```

---

# Stage 0 — Concept and invariants ✅

Established:

- game-development-only scope;
- prompt-driven development;
- persistent goal;
- research requirement;
- `UPLOAD/`;
- reversible Git workflow;
- build/run/test evidence;
- completion based on acceptance, not compilation;
- automated repair loop;
- regression protection;
- distinction between real blockers and fake completion.

Exit condition: architecture principles documented.

Status: **complete enough to build upon**.

---

# Stage 1 — Runnable local MVP ✅

Implemented:

- Python local server;
- browser dashboard;
- basic project creation;
- Codex execution loop;
- build/test command hooks;
- logs;
- generic OpenCV monitoring;
- Git checkpointing.

Exit condition: GameForge can run as a local application rather than only documentation.

Status: **complete enough to build upon**.

---

# Stage 2 — One-launch environment bootstrap ✅

Implemented in prior bootstrap generations:

- Windows environment setup;
- Python detection;
- Git;
- Node;
- Codex CLI;
- venv;
- dependencies;
- dashboard launch.

Critical Windows parser problem was fixed by delegating bootstrap complexity from CMD to PowerShell.

Exit condition: user reaches running dashboard through a single launcher.

Status: **validated on the user's Windows machine in v0.4.1 lineage**.

Note: the final single-file architecture supersedes most of this bootstrap as end-user packaging.

---

# Stage 3 — Desktop + `.gfai` project architecture ✅

Implemented:

- projects can live outside application directory;
- `.gfai` entry point;
- relative root resolution;
- project registry;
- project indexing;
- external project open;
- desktop packaging architecture;
- single app managing many projects.

Exit condition: a project can be represented independently from the application.

Status: **implemented**.

---

# Stage 4 — Native single-file CI stabilization 🟨 CURRENT

Goal:

Produce one native executable per supported OS/architecture.

### Completed within this stage

✅ PyInstaller one-file specification  
✅ embedded web resources  
✅ minimal source tree  
✅ source smoke test  
✅ native build matrix design  
✅ Windows x64 target  
✅ Linux x64 target  
✅ Linux ARM64 target  
✅ macOS Intel target  
✅ macOS ARM64 target  
✅ remove unsupported/unreliable Windows ARM64 target for now  
✅ dependency install split for diagnostics  
✅ move to Python 3.12 CI target  
✅ replace PyAutoGUI with pynput  
✅ fix duplicate YAML `env` key  
✅ support both repository-root and `GameForgeAI/` nested source layout  
✅ fix `tests/smoke.py` import root

### Still required

⬜ rerun all native jobs after v1.0.4  
⬜ confirm all dependency import checks  
⬜ confirm PyInstaller succeeds on every target  
⬜ confirm executable rename step  
⬜ confirm frozen executable startup test  
⬜ confirm `/api/status` from frozen app  
⬜ confirm web resource loads from frozen app  
⬜ verify final artifacts are executable  
⬜ check artifact sizes  
⬜ document any target-specific warnings

### Exit condition

Every supported target is green in the same source revision.

---

# Stage 5 — v1.0 Alpha release verification ⬜

After CI is green:

- download every native artifact;
- Windows x64 manual launch;
- Linux x64 manual launch;
- ARM runners validated in CI;
- macOS architecture startup validated in CI;
- create project;
- open `.gfai`;
- index project;
- run basic status;
- verify local user-data folder;
- verify project registry;
- verify browser launch;
- verify no unpacked source required.

Exit condition:

A GitHub release can contain binaries only and those binaries pass baseline application tests.

---

# Stage 6 — Core runtime hardening ⬜

Tasks:

- singleton/port collision handling;
- graceful shutdown;
- structured logging;
- crash handler;
- better frontend error states;
- API response schema consistency;
- persistent runtime metadata;
- safe background thread lifecycle;
- managed process log-handle cleanup;
- stale project registry cleanup;
- project migration strategy;
- large-project indexing optimization;
- path edge-case testing;
- Unicode path testing;
- network-drive behavior documentation.

---

# Stage 7 — Toolchain auto-discovery ⬜

Tasks:

- inspect project type;
- detect installed build tools;
- detect missing dependencies;
- map dependency to install method;
- avoid changing machine without user authorization;
- recognize proprietary/licensed dependencies;
- write toolchain status report;
- let AI configure `commands.build/test/launch`.

Exit condition:

A new project can go from minimal prompt/files to a correctly identified toolchain more reliably.

---

# Stage 8 — Autonomous QA expansion ⬜

Tasks:

- semantic CV;
- controller automation;
- input recording;
- expected-screen assertions;
- crash dialog detection;
- process hang detection;
- performance telemetry;
- screenshot evidence;
- test sequence library.

Exit condition:

GameForge can verify meaningful gameplay states, not only black/frozen frames.

---

# Stage 9 — Asset transformation pipeline ⬜

Tasks:

- deep mesh inspection;
- texture inspection;
- Blender automation;
- target budget analysis;
- style adaptation;
- collision;
- LOD;
- export;
- in-game verification.

Exit condition:

Uploaded assets can be transformed into technically and visually appropriate derivatives through a repeatable pipeline.

---

# Stage 10 — Engine/project adapters ⬜

Priority adapters:

1. generic native game project;
2. decomp/ROM;
3. Unity;
4. Unreal;
5. Godot;
6. Minecraft modding;
7. Source/Titanfall-family modding;
8. additional user-requested projects.

Each adapter defines:

- detection;
- dependencies;
- build;
- test;
- launch;
- logs;
- assets;
- expected runtime states;
- common failures.

---

# Stage 11 — Security and project trust ⬜

Required before calling the system broadly production-safe.

Tasks:

- trusted/untrusted project state;
- script/executable execution consent;
- network access state;
- file-scope policy;
- downloaded file quarantine;
- provenance;
- external binary approval;
- credential redaction;
- clearer LAN security.

---

# Stage 12 — v1.0 Release Candidate ⬜

Requirements:

- all Stage 4/5 targets stable;
- project lifecycle stable;
- no known critical data-loss bug;
- regression test suite;
- upgrade/migration docs;
- contributor docs;
- clean GitHub release;
- known limitations clearly documented.

---

# Stage 13 — v1.0 Stable ⬜

Definition:

GameForge core is stable enough that feature development can continue without regularly rebuilding fundamental packaging/project assumptions.

This does **not** mean every possible game project is guaranteed to succeed.

It means:

- GameForge application itself is stable;
- supported platforms are verified;
- project format is stable;
- failure states are diagnosable;
- game-specific problems are separated from core application problems.

---

# Project-template track

This runs alongside core development.

## Campaign continuation

🟨 Template exists  
⬜ dedicated adapter support  
⬜ mission regression framework  
⬜ semantic objective/mission detectors

## Game fusion

🟨 Template exists  
⬜ architecture-decomposition assistant  
⬜ performance budget system  
⬜ source/target system mapping

## Decomp/ROM transformation

🟨 Template exists  
⬜ toolchain adapter  
⬜ ROM/base input verifier  
⬜ emulator adapter  
⬜ deterministic gameplay test harness  
⬜ asset conversion integration

---

# Rule for moving the CURRENT marker

Do not move the CURRENT marker merely because code was written.

Move it only when the stage's exit condition has evidence.

For Stage 4, that means a green native build/test matrix.
