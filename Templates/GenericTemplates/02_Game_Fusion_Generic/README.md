# Generic Game Fusion Template

Use this when you want to recreate the playstyle/mechanics of one game inside another engine or moddable game.

Example:
> Make Minecraft-style player movement, block placement, inventory, and building inside BeamNG.drive while preserving BeamNG's world and vehicle physics.

## Think in systems

GameForge should break the request into parts such as:
- first-person/third-person controller;
- camera;
- interaction/raycasting;
- inventory;
- crafting;
- blocks/voxels;
- physics;
- AI;
- UI;
- persistence;
- world generation;
- vehicle interaction;
- audio;
- multiplayer if requested.

## Vertical slice first

A good first slice might be:
1. spawn player;
2. move;
3. look around;
4. interact with one object/block;
5. save/reload;
6. verify visually;
7. regression-test the base game.

Then expand.
