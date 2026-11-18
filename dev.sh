#!/bin/bash
# Development without a Raspberry Pi: aroiod with simulated hardware + the app.
#
#   ./dev.sh            app:        http://localhost:5173
#                       simulator:  http://localhost:5173/sim.html
#   ./dev.sh test       backend tests, svelte-check (incl. accessibility), build
#   ./dev.sh build      build the app and serve it from aroiod: http://localhost:8140 (/sim)
#   ./dev.sh reset      throw away the simulated device's data (.dev/)
#
# On a real Aroio (SSH as root, development image or your key in /root/.ssh/authorized_keys):
#   ./dev.sh deploy           aroiod + app to the device (/data/dev), restarts aroiod. Seconds.
#                             Stays active across reboots until the next system update.
#   ./dev.sh deploy --no-web  only aroiod (skips building the app)
#   ./dev.sh deploy --off     back to the code of the installed system
#   ./dev.sh deploy --bundle  build the whole system in Docker (incremental) and install it with
#                             RAUC into the other slot, then reboot: for units, scripts, packages,
#                             kernel. Only partition layout changes need a new SD card.
#   ./dev.sh logs             follow aroiod's log on the device
#
# Environment: PORT (app, 5173), API_PORT (aroiod, 8140), MODEL (AroioLT), BOARD (pi4),
#              AROIO_HOST (device for deploy/logs, aroio.local)
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

HOST="${AROIO_HOST:-aroio.local}"
on_device() { ssh -o ConnectTimeout=5 ${AROIO_SSH_OPTS:-} "root@$HOST" "$@"; }   # AROIO_SSH_OPTS: extra ssh options

deploy() {
    local web=1
    case "${1:-}" in
    --off)
        on_device 'rm -f /data/dev/active; systemctl restart aroiod'
        echo "$HOST nutzt wieder den Code des installierten Systems."
        return ;;
    --bundle)
        make docker-image
        local bundle
        bundle=$(ls -t output/aroio-*.raucb | head -1)
        echo "Installiere $bundle auf $HOST …"
        on_device 'mkdir -p /data/update && cat > /data/update/dev.raucb' < "$bundle"
        on_device 'rauc --mount=/run/rauc install /data/update/dev.raucb; rc=$?; rm -f /data/update/dev.raucb; [ $rc = 0 ] && /usr/lib/aroio/reboot'
        echo "$HOST startet mit dem neuen System. Startet es nicht sauber, geht es nach spätestens 5 Minuten zurück."
        return ;;
    --no-web) web=0 ;;
    "") ;;
    *) sed -n '2,21p' "$0"; exit 1 ;;
    esac
    [ $web = 1 ] && (cd web && npx vite build >/dev/null)
    local stage
    stage=$(mktemp -d)
    mkdir -p "$stage/aroiod"
    cp aroiod/*.py "$stage/aroiod/"
    [ $web = 1 ] && cp -R web/dist "$stage/web"
    # copy, then switch over in one step; base = system version the code is meant for
    tar -C "$stage" -cf - . | on_device '
        set -e
        rm -rf /data/dev.new && mkdir -p /data/dev.new && tar -C /data/dev.new -xf -
        [ -d /data/dev.new/web ] || { [ -d /data/dev/web ] && cp -a /data/dev/web /data/dev.new/; } || true
        cat /etc/aroio-version > /data/dev.new/base
        touch /data/dev.new/active
        rm -rf /data/dev.old; [ -d /data/dev ] && mv /data/dev /data/dev.old; mv /data/dev.new /data/dev; rm -rf /data/dev.old
        if [ ! -x /usr/lib/aroio/aroio-python ]; then
            # older image without aroio-python: runtime drop-in (gone after reboot)
            mkdir -p /run/systemd/system/aroiod.service.d
            printf "[Service]\nWorkingDirectory=/data/dev\nEnvironment=AROIO_STATIC=/data/dev/web\n" > /run/systemd/system/aroiod.service.d/dev.conf
            systemctl daemon-reload
        fi
        systemctl restart aroiod
        systemctl try-restart aroio-netjack'
    rm -rf "$stage"
    echo "Entwicklerstand läuft auf http://$HOST (zurück: ./dev.sh deploy --off)"
}

case "${1:-run}" in
deploy)
    shift
    deploy "$@"
    ;;
logs)
    on_device 'journalctl -f -u aroiod -u camilladsp -u aroio-netjack -n 50'
    ;;
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
    sed -n '2,21p' "$0"
    exit 1
    ;;
esac
