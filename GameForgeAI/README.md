# GameForge AI — Single-File Release Source

This is the minimal source tree used to build GameForge AI.

## Release policy

Public GitHub Releases contain binaries only:

- `GameForgeAI-Windows-x64.exe`
- `GameForgeAI-Windows-arm64.exe`
- `GameForgeAI-Linux-x64`
- `GameForgeAI-Linux-arm64`
- `GameForgeAI-macOS-x64`
- `GameForgeAI-macOS-arm64`

The executable contains the Python runtime, GameForge server, web UI, OpenCV and
the packaged Python dependencies. Users do not install Python packages.

GameForge still uses authorized external game-development tools when a project
requires them. Codex CLI/Git/SDKs/compilers/emulators are project/toolchain
dependencies and may require installation, authentication, licenses, or user
approval. No single executable can legally or technically embed every third-party
game SDK, compiler, commercial tool, emulator, or proprietary engine.

## `.gfai`

Run:
`GameForgeAI path/to/project.gfai`

Windows/Linux can register this binary as the `.gfai` handler externally.
A raw one-file macOS Mach-O executable can accept `.gfai` paths, but Finder-native
document association requires an `.app` bundle; that is incompatible with the
literal one-file release requirement.

## Build

Tag the GitHub repository (`v1.0.0`, etc.) or manually run the workflow. Native
GitHub runners build and smoke-test each binary before publication.

PyInstaller requires building separately on each OS; cross-OS binaries are not
produced from one host.


## v1.0.1 CI compatibility fix

- Uses `actions/checkout@v7` and `actions/setup-python@v7` (Node 24 generation).
- Builds with Python 3.12 for broad native-wheel compatibility.
- Pins PyInstaller 6.22.3.
- Replaces the aging PyAutoGUI build dependency with pynput 1.8.2.
- Splits dependency installation into separate logged steps.
- Removes the Windows ARM64 release target for now because current `opencv-python`
  releases do not provide a Windows ARM64 wheel; publishing that binary as fully
  supported would be misleading.
- Keeps Windows x64, Linux x64/ARM64, and macOS x64/ARM64.
