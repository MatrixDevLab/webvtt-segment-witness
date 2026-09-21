from __future__ import annotations

import argparse
import json
from pathlib import Path

from .witness import render_json, validate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a local segmented WebVTT/HLS timing contract")
    parser.add_argument("playlist", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit deterministic JSON")
    args = parser.parse_args(argv)
    result = validate(args.playlist)
    if args.as_json:
        print(render_json(result), end="")
    else:
        state = "valid" if result["valid"] else "invalid"
        print(f"{state}: {result['playlist']}")
        for item in result["diagnostics"]:
            where = item["segment"] or "playlist"
            line = f":{item['line']}" if item["line"] else ""
            print(f"{item['severity']}: {item['code']} ({where}{line}) {item['message']}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
