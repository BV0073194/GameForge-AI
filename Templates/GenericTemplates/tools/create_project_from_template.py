from __future__ import annotations
import argparse, shutil, json, re
from pathlib import Path

def slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", s.strip()).strip("-").lower()
    return s or "gameforge-project"

def main():
    ap = argparse.ArgumentParser(description="Create a GameForge project from a template.")
    ap.add_argument("template", choices=["campaign","fusion","rom"])
    ap.add_argument("name")
    ap.add_argument("destination")
    args = ap.parse_args()

    here = Path(__file__).resolve().parents[1]
    mapping = {
        "campaign": here/"01_Campaign_Continuation_Generic",
        "fusion": here/"02_Game_Fusion_Generic",
        "rom": here/"03_Decomp_ROM_Transformation_Generic",
    }
    src = mapping[args.template]
    dest = Path(args.destination).expanduser().resolve()
    if dest.exists():
        raise SystemExit(f"Destination already exists: {dest}")
    shutil.copytree(src, dest)

    cfg_path = dest/"gameforge.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    pid = slug(args.name)
    cfg["id"] = pid
    cfg["name"] = args.name
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    for f in dest.glob("*.gfai"):
        f.unlink()
    manifest = {
        "format":"GameForgeAI.Project",
        "format_version":1,
        "project_id":pid,
        "name":args.name,
        "root":".",
        "config":"gameforge.json",
        "goal":"goal.md",
        "uploads":"UPLOAD",
        "project_index":".gameforge/project_index.json",
    }
    out = dest/f"{slug(args.name)}.gfai"
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(out)

if __name__ == "__main__":
    main()
