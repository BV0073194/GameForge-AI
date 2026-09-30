# GameForge AI Project Templates v1

This repository is a starter-template pack for GameForge AI desktop projects.

It contains three generic project types based on the use cases GameForge was designed for:

1. **Campaign Continuation** — add new missions/campaign content to an existing game.
2. **Game Fusion** — recreate the gameplay systems of one game inside another engine/project.
3. **Decomp / ROM Transformation** — transform a decomp/homebrew/ROM-based game project into a new playable experience.

These templates are intended to be understandable by someone with no prior modding or game-development experience.

## Important reality check

No template can guarantee a perfect result for every game, engine, ROM, SDK, or proprietary title.

GameForge is designed to maximize reliability by:
- researching before guessing;
- verifying APIs/toolchains;
- preserving the last known-good state;
- building and running repeatedly;
- using logs, crash data, OpenCV, screenshots, process state, and input-replay tests;
- regression-testing existing gameplay;
- recording real blockers instead of pretending a feature works.

That is the standard these templates enforce.

## Basic workflow

For any template:

1. Copy the template folder.
2. Rename the folder and `.gfai` file.
3. Open `PROJECT_SETUP.md`.
4. Put any useful files in `UPLOAD/`.
5. Fill in the goal in `goal.md`.
6. Edit `gameforge.json` only if needed.
7. Double-click the `.gfai` file after GameForge AI is installed.
8. Start the autonomous developer.
9. Let GameForge research, implement, build, test, observe, repair, and regression-test.

## Included templates

- `01_Campaign_Continuation_Generic/`
- `02_Game_Fusion_Generic/`
- `03_Decomp_ROM_Transformation_Generic/`

## What belongs in UPLOAD

You may provide:
- source code
- public Git repositories
- mods
- decomp projects
- legal personal ROMs for local workflows
- models
- textures
- animations
- audio
- maps
- tools
- screenshots/video references
- documentation
- design notes

GameForge should never overwrite originals in `UPLOAD/`.

## Recommended GitHub layout

You can publish this template repository publicly.

Do NOT upload:
- commercial ROMs
- proprietary game files
- stolen/private source code
- credentials/API keys
- copyrighted assets you do not have permission to redistribute

Use `.gitignore` and local-only folders for those.
