#!/usr/bin/env python3
"""CI docs check: every local file referenced in README.md must exist on disk.

Scans README.md for Markdown links/images pointing at relative paths in the repo
(docs/..., schema/..., examples/..., assets/..., *.md) and fails if any target
is missing -- so a doc link can never silently rot.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

# Markdown link/image targets: [text](target) and ![alt](target).
_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")

# Only check links that look like local repo paths (skip http(s), anchors, mailto).
_LOCAL_PREFIXES = ("docs/", "schema/", "examples/", "assets/", "./", "../")


def main() -> int:
    text = README.read_text(encoding="utf-8")
    missing: list[str] = []
    checked = 0
    for target in _LINK_RE.findall(text):
        target = target.split("#", 1)[0].split(" ", 1)[0].strip()
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (target.startswith(_LOCAL_PREFIXES) or target.endswith(".md")):
            continue
        checked += 1
        if not (ROOT / target).exists():
            missing.append(target)
    if missing:
        print("Missing files referenced by README.md:", file=sys.stderr)
        for m in sorted(set(missing)):
            print(f"  - {m}", file=sys.stderr)
        return 1
    print(f"README links OK ({checked} local target(s) checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
