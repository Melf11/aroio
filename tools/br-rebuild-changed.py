#!/usr/bin/env python3
"""Buildroot does not rebuild a package when its options change (e.g. python3 with
BR2_PACKAGE_PYTHON3_PYEXPAT). Compares .config with the one of the last image build and
runs <package>-dirclean for every built package whose symbols changed.

    tools/br-rebuild-changed.py OUT          (before `make`, after the defconfig)
    tools/br-rebuild-changed.py OUT --done   (after a successful build: remember .config)
"""
import json
import subprocess
import sys
from pathlib import Path


def symbols(path):
    out = {}
    try:
        for line in Path(path).read_text().splitlines():
            if line.startswith("BR2_PACKAGE_") and "=" in line:
                k, v = line.split("=", 1)
                out[k] = v
            elif line.startswith("# BR2_PACKAGE_") and line.endswith(" is not set"):
                out[line[2:-11]] = "n"
    except OSError:
        pass
    return out


def main():
    out = Path(sys.argv[1])
    last = out / ".config.last-image"
    if "--done" in sys.argv:
        last.write_text((out / ".config").read_text())
        return
    if not last.exists():
        return                                   # first build: everything is built anyway
    old, new = symbols(last), symbols(out / ".config")
    changed = {k for k in old.keys() | new.keys() if old.get(k, "n") != new.get(k, "n")}
    if not changed:
        return
    try:
        built = json.loads((out / "show-info.json").read_text())
    except (OSError, ValueError):
        built = {}
    names = sorted(built, key=len, reverse=True)
    todo = set()
    for sym in changed:
        for name in names:                       # longest match: PYTHON3_PYEXPAT -> python3
            prefix = "BR2_PACKAGE_" + name.upper().replace("-", "_")
            if sym == prefix or sym.startswith(prefix + "_"):
                if any((out / "build").glob(f"{name}-*")):
                    todo.add(name)
                break
    for name in sorted(todo):
        print(f"Optionen von {name} geändert: wird neu gebaut")
        subprocess.run(["make", "-s", "-C", str(out), f"{name}-dirclean"], check=True)


if __name__ == "__main__":
    main()
