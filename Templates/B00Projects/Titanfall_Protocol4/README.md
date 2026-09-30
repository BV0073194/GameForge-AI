# Titanfall: Protocol 4 — GameForge AI Project

This folder is a ready-to-open GameForge project for the fan-made Titanfall 2 campaign continuation we designed.

## What it is supposed to make

A full playable single-player continuation to Titanfall 2 centered on Jack Cooper and BT.

Planned mission framework:

1. Ghost in the Machine
2. Residual
3. Recovery
4. Protocol Zero
5. The Apex Predator
6. Dead Frontier
7. Echoes of Typhon
8. Legends
9. The Last Vanguard
10. Protocol 4

The names/story beats are project-original unless research confirms otherwise.

## Beginner setup

1. Install GameForge AI Desktop.
2. Make sure you legally own and have Titanfall 2 installed on PC.
3. Put any useful local files, existing mods, logs, references, or additional tools into the matching `UPLOAD/` folders.
4. Double-click `Titanfall_Protocol4.gfai`.
5. In GameForge, verify the project root and read the goal/acceptance criteria.
6. Start the autonomous developer.

## What GameForge should do first

It should NOT immediately try to write ten missions.

It should first:
- detect the Titanfall 2 installation;
- fetch/update the preferred public Northstar repositories/docs;
- establish a known-good launch;
- verify what is actually possible in single-player;
- create a tiny playable vertical slice;
- build/launch/test it;
- use logs + OpenCV + screenshots + process state;
- only then expand.

## What "complete" means

The project is not done because scripts compile.

The requested campaign must be playable and the acceptance file must have evidence for the critical requirements. Later missions must not silently break earlier missions.

## Research standard

Use exhaustive/professional research. Prefer primary/upstream sources. Separate:
- established canon;
- developer statements;
- reported information;
- abandoned/cut concepts;
- community theories;
- project-original writing.

## Distribution

Do not put EA/Respawn proprietary game files in this Git repository. The finished mod/release should depend on the user's own legally installed Titanfall 2 where required.
