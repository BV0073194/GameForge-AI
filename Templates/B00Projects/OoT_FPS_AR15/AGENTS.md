# Agent Contract — Decomp / ROM Transformation

Rules:
- Prefer a public decomp/recomp/homebrew codebase.
- Never redistribute the original commercial ROM.
- Establish a clean reproducible base build before changing gameplay.
- Verify target hardware limits before importing modern/high-poly assets.
- Uploaded assets are source material, not necessarily final assets.
- Adapt geometry, textures, materials, animation, collision, scale, and rendering to the target.
- Preserve original uploads untouched.
- Prototype the requested transformation in the smallest test scene/room first.
- Build after small changes.
- Boot the generated output in an emulator.
- Use logs, screenshots/OpenCV, input replay, crash/freeze detection, and regression checks.
- Do not mark complete until the ROM/build boots and the requested player interaction actually works.
