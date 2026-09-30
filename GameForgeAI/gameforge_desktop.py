from __future__ import annotations
import sys
from pathlib import Path

def main() -> None:
    forwarded = ["gameforge"]
    rest = list(sys.argv[1:])
    if rest and Path(rest[0]).suffix.lower() == ".gfai":
        forwarded += ["--project-file", str(Path(rest.pop(0)).expanduser().resolve())]
    forwarded += rest
    sys.argv = forwarded
    from server.app import main as server_main
    server_main()

if __name__ == "__main__":
    main()
