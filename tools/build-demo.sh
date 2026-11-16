#!/bin/sh
# Demo for GitHub Pages: the app plus the simulated Aroio (aroiod --sim) running as Python
# in the browser (Pyodide). Result: web/dist-demo (aroiod.zip, 404.html for deep links).
#   AROIO_DEMO_BASE=/aroio/  path the site is served under (default: GitHub Pages of Melf11/aroio)
set -e
cd "$(dirname "$0")/.."
(cd web && npx vite build --mode demo)
python3 - <<'PY'
import zipfile, pathlib
root = pathlib.Path(".")
with zipfile.ZipFile("web/dist-demo/aroiod.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(root.glob("aroiod/**/*")):
        if f.is_file() and "__pycache__" not in f.parts and f.suffix in (".py", ".tgz", ".json"):
            z.write(f, f.as_posix())
PY
# GitHub Pages answers unknown paths (/aroio/klang) with 404.html: the app handles them
cp web/dist-demo/index.html web/dist-demo/404.html
rm -f web/dist-demo/sw.js
du -sh web/dist-demo web/dist-demo/aroiod.zip
