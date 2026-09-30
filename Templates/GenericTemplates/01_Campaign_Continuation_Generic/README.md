# Generic Campaign Continuation Template

Use this when you want GameForge to create new missions/campaign content for an existing game.

Examples:
- continue a finished single-player campaign;
- create a fan sequel inside the original engine;
- add new levels and story chapters;
- create an expansion-sized mod.

## What you should provide

Best case:
- installed game;
- modding SDK/framework;
- source/decomp if publicly available;
- useful public repositories;
- your design goals;
- optional assets/references.

You can still begin with only a prompt if public tooling is enough.

## Example prompt

> Continue this game's single-player campaign with 10 new missions. Deep-research verified developer interviews, abandoned concepts, lore, public modding code, engine limitations, and community technical research. Preserve the original game's tone and mechanics. Build each mission, launch it, use logs/OpenCV/crash data/input tests, regression-test all prior missions, and keep fixing until the full campaign is playable.

## Recommended first milestone

Do NOT start with the whole campaign.

First prove:
1. one custom mission/level can load;
2. one objective can progress;
3. one enemy encounter works;
4. one checkpoint/restart works;
5. the game can exit/transition cleanly.

Then expand.
