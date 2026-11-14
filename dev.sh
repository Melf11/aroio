#!/bin/bash
# Development without a Raspberry Pi: aroiod with simulated hardware + the app.
#
#   ./dev.sh            app:        http://localhost:5173
#                       simulator:  http://localhost:5173/sim.html
#   ./dev.sh test       backend tests, svelte-check (incl. accessibility), build
#   ./dev.sh build      build the app and serve it from aroiod: http://localhost:8140 (/sim)
#   ./dev.sh reset      throw away the simulated device's data (.dev/)
#
# Environment: PORT (app, 5173), API_PORT (aroiod, 8140), MODEL (AroioLT), BOARD (pi4)
set -euo pipefail
cd "$(dirname "$0")"
DEV="$PWD/.dev"
API_PORT="${API_PORT:-8140}"
PORT="${PORT:-5173}"

if [ ! -x .venv/bin/python ]; then
    echo "Richte Python-Umgebung ein (.venv) …"
    python3 -m venv .venv
    .venv/bin/pip install -q -r requirements-dev.txt
fi
if [ ! -d web/node_modules ]; then
    echo "Installiere Web-Abhängigkeiten …"
    (cd web && npm ci --no-audit --no-fund)
fi

aroiod() {
    .venv/bin/python -m aroiod --sim --data "$DEV/data" --host 127.0.0.1 --port "$API_PORT" \
        --model "${MODEL:-AroioLT}" --board "${BOARD:-pi4}" "$@"
}

case "${1:-run}" in
test)
    .venv/bin/python -m pytest -q
    (cd web && npx svelte-check --fail-on-warnings && npx vite build >/dev/null && node ../tools/i18n-check.mjs)
    echo "Alles grün."
    ;;
build)
    (cd web && npx vite build)
    echo "App + Simulator: http://localhost:$API_PORT  (Simulator: http://localhost:$API_PORT/sim)"
    aroiod --static web/dist
    ;;
reset)
    rm -rf "$DEV"
    echo "Simulierte Gerätedaten gelöscht."
    ;;
run)
    mkdir -p "$DEV"
    aroiod --static /nonexistent &
    API_PID=$!
    trap 'kill $API_PID 2>/dev/null' EXIT INT TERM
    echo
    echo "  App:        http://localhost:$PORT"
    echo "  Simulator:  http://localhost:$PORT/sim.html"
    echo
    (cd web && AROIOD="http://127.0.0.1:$API_PORT" npx vite --port "$PORT" --strictPort)
    ;;
*)
    sed -n '2,12p' "$0"
    exit 1
    ;;
esac
