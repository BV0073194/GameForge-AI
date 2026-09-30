# OoT FPS + AR-15 — GameForge AI Project

This is the ready-to-open GameForge project for the exact OoT experiment we discussed.

## Goal

Turn the N64 Ocarina of Time decomp project into an FPS-style experience beginning with the uploaded AR-15.

The rifle should:
- be visible in Link's House;
- be in the room where Link begins a new game;
- be collectible;
- become usable;
- support the complete intended aiming/firing/damage/ammo/UI/save experience;
- visually fit OoT instead of looking like an untouched modern asset.

## What is already included

The user's uploaded `low-poly-assault-rifle.zip` is staged under `UPLOAD/MODELS/`.

If extractable, its contained model/texture are also copied into the canonical model/texture upload folders.

## What you still need locally

A legally obtained supported OoT base ROM/input required by the current zeldaret/oot build process.

Put it only in:

`UPLOAD/ROMS_LOCAL/`

Do not publish that ROM to GitHub.

## Beginner setup

1. Install GameForge AI Desktop.
2. Copy this entire project folder somewhere writable.
3. Put your supported OoT base ROM/input into `UPLOAD/ROMS_LOCAL/`.
4. Double-click `OoT_FPS_AR15.gfai`.
5. Review the goal and acceptance criteria.
6. Start the autonomous developer.

## What GameForge should do first

It should:
1. fetch/update the current zeldaret/oot repo and preferred public docs;
2. verify the exact required base ROM/input and toolchain;
3. establish a clean build before touching gameplay;
4. inspect how Link's House is represented in the current source;
5. analyze the rifle model;
6. create an OoT/N64-appropriate derivative;
7. make only the pickup proof first;
8. build and boot;
9. visually verify it;
10. then add the complete weapon system incrementally.

## Asset-quality rule

The uploaded rifle is source material.

GameForge should preserve the original and generate working derivatives as needed:
- lower/simplify geometry;
- adapt textures;
- reduce/merge materials;
- adjust scale;
- create held/pickup variants;
- create appropriate collision;
- adapt animation/attachment;
- preserve recognizable silhouette;
- fit OoT/N64 technical and visual constraints.

## Completion rule

The project is NOT complete just because a ROM builds.

The actual gameplay path must work and have evidence in `.gameforge/acceptance.json`.
