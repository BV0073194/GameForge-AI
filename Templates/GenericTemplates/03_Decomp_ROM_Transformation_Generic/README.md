# Generic Decomp / ROM Transformation Template

Use this for projects like:
- convert an older game into an FPS;
- add new weapons/mechanics to an N64 title;
- heavily modify a decomp project;
- create a total conversion using a classic game's engine.

## Example prompt

> Turn this N64 action-adventure game into a first-person shooter. Use the uploaded rifle model, but adapt it to the game's original poly count, texture style, and N64 constraints. Put the pickup in the player's starting room. Implement the complete weapon experience, build the ROM, boot it in an emulator, visually verify it, regression-test the opening sequence, and keep fixing until it is playable.

## Upload suggestions

- decomp/source tree in `UPLOAD/SOURCE/`
- public repositories in `UPLOAD/REPOS/`
- personal legal ROM in `UPLOAD/ROMS_LOCAL/`
- models in `UPLOAD/MODELS/`
- textures in `UPLOAD/TEXTURES/`
- screenshots/art references in `UPLOAD/REFERENCE/`
- docs/tools in `UPLOAD/DOCS/` and `UPLOAD/TOOLS/`

## Asset adaptation

A modern model should not be blindly inserted.

GameForge should determine:
- target poly budget;
- texture resolution;
- material/shader limitations;
- scale;
- attachment/animation requirements;
- collision;
- held/world pickup variants;
- performance.

Then create a derivative that fits the game naturally.
