# Project Setup — Beginner Guide

You do not need to understand the whole codebase before using this template.

## 1. What a `.gfai` file is

The `.gfai` file is the GameForge project entry point.

Think of it like a Unity project launcher file.

When opened, it tells GameForge:
- which folder is the project root;
- where the main GameForge config is;
- where the goal is stored;
- where uploads/assets live;
- where the project index should be written.

The `.gfai` file itself does not contain the whole game.

## 2. What `gameforge.json` is

This is the main GameForge configuration.

It controls things such as:
- project name;
- research depth;
- internet research;
- build/test/launch commands;
- OpenCV settings;
- log locations;
- autonomous iteration rules.

Most users should not need to edit much manually.

## 3. What `goal.md` is

This is the human-readable project request.

Write what you want in normal language.

Be specific about:
- what the player should be able to do;
- what should be preserved;
- what visual style you want;
- what should count as complete.

## 4. What `acceptance.json` is

This prevents the AI from stopping too early.

A project is not complete just because the code compiles.

Each requirement must have evidence.

Typical evidence includes:
- successful build;
- game launches;
- expected object appears;
- player can interact with it;
- logs are clean enough;
- OpenCV screenshot confirms the expected result;
- regression tests pass.

## 5. What `UPLOAD/` is for

Drop useful materials here.

GameForge should treat these as inputs, not as files to modify directly.

Examples:
- `UPLOAD/SOURCE/`
- `UPLOAD/REPOS/`
- `UPLOAD/MODELS/`
- `UPLOAD/TEXTURES/`
- `UPLOAD/DOCS/`
- `UPLOAD/REFERENCE/`

## 6. Internet research

If research mode is `exhaustive`, GameForge should search broadly across public/authorized sources when needed.

Examples:
- official docs;
- source repositories;
- engine docs;
- modding docs;
- archived developer notes;
- public dev interviews;
- old public documentation;
- issue trackers;
- technical talks;
- public reverse-engineering research.

It must separate:
- verified facts;
- developer statements;
- reported information;
- community theory;
- project-original ideas.

## 7. Safety / rollback

Every meaningful working milestone should be committed to Git.

If a later change breaks something, GameForge should:
- repair it, or
- roll back to the last known-good state and try another solution.

## 8. Visual testing

If the project is interactive, GameForge should use:
- OpenCV;
- screenshots;
- game-window capture;
- freeze detection;
- black-screen detection;
- crash detection;
- scripted keyboard/mouse/controller input where practical.

## 9. When the AI should stop

Only when:
- acceptance criteria pass, or
- a genuine technical/external blocker is proven.

A blocker must be documented with evidence and alternatives.
