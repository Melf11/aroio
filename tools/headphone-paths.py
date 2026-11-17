#!/usr/bin/env python3
"""Refresh aroiod/headphone_paths.py from GitHub (needs the gh CLI)."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from aroiod import headphones  # noqa: E402

tree = json.loads(subprocess.check_output(
    ["gh", "api", f"repos/{headphones.REPO}/git/trees/{headphones.BRANCH}?recursive=1"]))
paths = sorted(i["path"] for c in headphones.parse_tree(tree) for i in c["items"])
target = ROOT / "aroiod" / "headphone_paths.py"
head = target.read_text().split("PATHS = (")[0]
target.write_text(head + "PATHS = (\n" + "".join(f"    {p!r},\n" for p in paths) + ")\n")
print(f"{len(paths)} filters")
