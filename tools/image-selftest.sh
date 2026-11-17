#!/bin/sh
# Checks a built image without hardware (runs in the aarch64 build container):
# programs present, CamillaDSP accepts the configs aroiod generates, aroiod
# starts in real mode and serves app + API.
#   docker run --rm -v "$PWD":/work -v aroio-build:/build -w /work aroio-build tools/image-selftest.sh
set -eu
R=/tmp/aroio-root
rm -rf "$R"
/build/out/host/bin/unsquashfs -q -d "$R" /build/out/images/rootfs.squashfs >/dev/null
fail=0
for f in usr/bin/camilladsp usr/bin/squeezelite usr/bin/shairport-sync usr/bin/upmpdcli usr/bin/bluealsad usr/bin/bluealsactl \
         usr/bin/iwctl usr/bin/rauc usr/bin/aroio-event usr/lib/aroiod/aroiod/real.py usr/share/aroio-web/index.html \
         etc/rauc/system.conf etc/rauc/keyring.pem etc/systemd/system/multi-user.target.wants/aroiod.service \
         etc/systemd/system/multi-user.target.wants/camilladsp.service \
         usr/sbin/hostapd usr/sbin/dnsmasq usr/sbin/iw usr/lib/firmware/regulatory.db etc/iwd/main.conf \
         usr/lib/systemd/system/aroio-hotspot.service usr/lib/systemd/system/aroio-portal-dns.service \
         usr/lib/systemd/system/iwd.service.d/aroio.conf usr/lib/systemd/system/bluetooth.service.d/aroio.conf \
         usr/bin/bt-agent usr/bin/bluetoothctl etc/bluetooth/main.conf \
         etc/systemd/system/multi-user.target.wants/nqptp.service \
         etc/systemd/system/multi-user.target.wants/shairport-sync.service \
         etc/systemd/system/multi-user.target.wants/bluetooth.service \
         etc/systemd/system/multi-user.target.wants/bluealsa.service \
         etc/systemd/system/multi-user.target.wants/bluealsa-aplay.service \
         etc/systemd/system/multi-user.target.wants/aroio-bt-agent.service \
         usr/bin/pulseaudio usr/lib/systemd/system/aroio-pulse.service usr/lib/systemd/system/aroio-soloist.service \
         etc/systemd/system/multi-user.target.wants/aroio-soloist.service etc/aroio/pulse.pa usr/lib/libatomic.so.1 \
         usr/lib/aroiod/aroiod/soloist.py usr/lib/systemd/system/aroio-soloist-update.timer \
         etc/systemd/system/multi-user.target.wants/squeezelite.service etc/systemd/system/multi-user.target.wants/upmpdcli.service \
         etc/systemd/system/multi-user.target.wants/aroio-infoscreen.service usr/lib/aroio/infoscreen \
         etc/systemd/system/data.mount.wants/aroio-grow-data.service usr/sbin/sfdisk usr/bin/partx usr/lib/systemd/systemd-growfs \
         usr/share/aroio/filters/BBCDipL96.dbl usr/share/aroio/filters/EchoR192.dbl usr/share/aroio/licenses.json \
         usr/lib/udev/rules.d/90-aroio-ir.rules usr/bin/ir-keytable \
         usr/share/aroio/boot/Image usr/share/aroio/boot/bcm2711-rpi-4-b.dtb usr/share/aroio/boot/bcm2710-rpi-3-b.dtb \
         usr/share/aroio/boot/overlays/iqaudio-dacplus.dtbo usr/share/aroio/boot/cmdline.txt.in \
         usr/lib/aroio/rauc-tryboot usr/lib/aroio/reboot usr/lib/aroio/aroio-python usr/lib/aroio/trial-watch \
         etc/systemd/system/multi-user.target.wants/aroio-trial-watch.service \
         usr/bin/jackd usr/lib/jack/netmanager.so usr/lib/jack/audioadapter.so usr/lib/jack/jack_dummy.so \
         usr/lib/systemd/system/aroio-netjack.service usr/lib/aroiod/aroiod/netjack.py usr/lib/aroiod/aroiod/updates.py \
         etc/ssl/certs/ca-certificates.crt usr/lib/aroio/announce usr/bin/arping \
         etc/systemd/system/multi-user.target.wants/aroio-announce.service; do
    target="$R/$f"
    if [ -L "$target" ]; then   # links point inside the image: absolute (from its root) or relative
        l=$(readlink "$target"); case "$l" in /*) target="$R$l";; *) target="$(dirname "$target")/$l";; esac
    fi
    [ -e "$target" ] || { echo "FEHLT: $f"; fail=1; }
done
[ -z "$(ls "$R/usr/share/aroio-web/assets" | grep sim || true)" ] || { echo "Simulator im Image"; fail=1; }
grep -q "^/dev/root / auto ro" "$R/etc/fstab" || { echo "Root nicht read-only in fstab"; fail=1; }
grep -q "LABEL=data.*x-systemd.growfs" "$R/etc/fstab" || { echo "/data wächst nicht mit (x-systemd.growfs)"; fail=1; }
[ -L "$R/etc/dropbear" ] && [ "$(readlink "$R/etc/dropbear")" = "/data/dropbear" ] || { echo "SSH-Hostschlüssel nicht auf /data"; fail=1; }
[ ! -d "$R/usr/lib/python3"*/site-packages/scipy ] 2>/dev/null || { echo "scipy noch im Image"; fail=1; }
SQ=$(stat -c %s /build/out/images/rootfs.squashfs)
[ "$SQ" -lt $((240 * 1024 * 1024)) ] || { echo "rootfs zu groß für die 256-MB-Slots: $SQ"; fail=1; }
echo "rootfs.squashfs: $((SQ / 1048576)) MB, Module: $(du -sm "$R/usr/lib/modules" | cut -f1) MB"
for u in squeezelite upmpdcli shairport-sync bluealsa-aplay aroio-pulse; do
    grep -rq "Loopback,0,0" "$R/usr/lib/systemd/system/$u.service" "$R/usr/lib/systemd/system/$u.service.d" "$R/etc/shairport-sync.conf" "$R/etc/mpd.conf" "$R/etc/aroio/pulse.pa" 2>/dev/null \
        || { echo "$u schreibt nicht in die Loopback"; fail=1; }
done
# pulseaudio --system refuses to start without its user ("Failed to find user 'pulse'")
grep -q "^pulse:" "$R/etc/passwd" || { echo "Benutzer pulse fehlt (aroio-pulse startet nicht)"; fail=1; }
# only Avahi speaks mDNS: a second stack in systemd-resolved makes aroio.local unreliable
grep -q "^MulticastDNS=no" "$R/etc/systemd/resolved.conf.d/aroio.conf" 2>/dev/null || { echo "systemd-resolved macht noch mDNS"; fail=1; }
[ "$(readlink "$R/etc/resolv.conf")" = "../run/systemd/resolve/stub-resolv.conf" ] || { echo "/etc/resolv.conf umgeht systemd-resolved (DNS bei LAN+WLAN kaputt)"; fail=1; }
for u in aroio-soloist aroio-soloist-update mpd upmpdcli; do grep -q "^EnvironmentFile=-/data/aroio/proxy.env" "$R/usr/lib/systemd/system/$u.service.d/proxy.conf" 2>/dev/null || { echo "$u: Proxy-Einstellung fehlt"; fail=1; }; done
# same DHCP identity after every restart (machine-id is new on every boot): same IP address
grep -q "^ClientIdentifier=mac" "$R/etc/systemd/network/20-wired.network" || { echo "DHCP-Kennung wechselt bei jedem Start (neue IP)"; fail=1; }
grep -q "^ConditionPathExists=!/data/aroio/wifi-off" "$R/usr/lib/systemd/system/iwd.service.d/wifi-off.conf" 2>/dev/null || { echo "WLAN-Schalter wirkt nach Neustart nicht (iwd-Drop-in fehlt)"; fail=1; }
grep -q -- "--volume=none" "$R/usr/lib/systemd/system/bluealsa-aplay.service.d/aroio.conf" || { echo "bluealsa-aplay ohne --volume=none (bricht ohne Mixer ab)"; fail=1; }
ls "$R"/usr/lib/firmware/brcm/BCM4345C0*.hcd >/dev/null 2>&1 || { echo "Bluetooth-Firmware Pi 4 (BCM4345C0) fehlt"; fail=1; }
grep -q "^root:[*!]" "$R/etc/shadow" || { echo "root hat ein leeres Passwort (dropbear lehnt dann auch Schlüssel ab)"; fail=1; }
if [ "$(cat "$R/etc/aroio-version")" = "dev" ]; then
    [ -s "$R/root/.ssh/authorized_keys" ] || { echo "SSH-Schlüssel fehlt im Entwicklungs-Image"; fail=1; }
fi
grep -q "rauc.slot=@SLOT@" "$R/usr/share/aroio/boot/cmdline.txt.in" || { echo "cmdline ohne Slot-Kennung"; fail=1; }
[ -z "$(ls -A "$R/boot" 2>/dev/null)" ] || { echo "Kernel doppelt in /boot"; fail=1; }
[ ! -e "$R/usr/bin/librespot" ] || { echo "librespot noch im Image"; fail=1; }
grep -q "BindPaths=/data/timesync" "$R/usr/lib/systemd/system/systemd-timesyncd.service.d/aroio.conf" 2>/dev/null || { echo "Uhrzeit wird nicht gespeichert"; fail=1; }
grep -q "org.gnome.ShairportSync" "$R/etc/dbus-1/system.d/shairport-sync-dbus.conf" 2>/dev/null || { echo "AirPlay ohne D-Bus-Fernsteuerung"; fail=1; }
grep -aq "5\.6\.[0-9]" "$R/usr/bin/shairport-sync" || { echo "shairport-sync ist nicht 5.6"; fail=1; }
# updates from GitHub need TLS in Python, and every image must trust the release key
chroot "$R" /usr/bin/python3 -c "import ssl, ctypes.util; ssl.create_default_context()" || { echo "Python ohne SSL"; fail=1; }
# every module must import with the device's Python (it lacks e.g. xml): lazy imports fail only when used
chroot "$R" /bin/sh -c 'cd /usr/lib/aroiod && /usr/bin/python3 -c "import importlib, pkgutil, aroiod; [importlib.import_module(\"aroiod.\" + m.name) for m in pkgutil.iter_modules(aroiod.__path__) if m.name != \"__main__\"]"' || { echo "aroiod-Modul laesst sich auf dem Geraet nicht importieren"; fail=1; }
grep -q "$(sed -n 2p br2-external/board/rpi/rauc/release-cert.pem)" "$R/etc/rauc/keyring.pem" || { echo "Release-Zertifikat fehlt im Keyring"; fail=1; }
[ -d "$R/usr/share/factory/var" ] || { echo "/var-Werkseinstellungen fehlen (read-only root)"; fail=1; }
ls "$R"/etc/systemd/network/*.network >/dev/null 2>&1 || { echo "keine Netzwerkkonfiguration (DHCP)"; fail=1; }
grep -q "BindPaths=/data/iwd:/var/lib/iwd" "$R/usr/lib/systemd/system/iwd.service.d/aroio.conf" || { echo "iwd speichert WLANs nicht auf /data"; fail=1; }
# every enabled unit must exist (a dangling link starts nothing, silently)
for l in "$R"/etc/systemd/system/*.wants/*; do
    t=$(readlink "$l"); [ "$t" = "/dev/null" ] && continue
    [ -e "$R$t" ] || { echo "aktivierte Unit fehlt: $(basename "$l")"; fail=1; }
done

# kernel modules must be loadable by the image's own kmod (compression!)
KVER=$(ls "$R/usr/lib/modules" | head -1)       # the image's kernel, not the build host's
[ -z "$(find "$R/usr/lib/modules" -name '*.ko.xz' -o -name '*.ko.zst' -o -name '*.ko.gz' | head -1)" ] \
    || { echo "Kernel-Module komprimiert (kmod im Image kann sie evtl. nicht laden)"; fail=1; }
for m in snd-aloop brcmfmac cfg80211 snd-soc-pcm512x-i2c snd-usb-audio; do
    chroot "$R" /sbin/modprobe -n -S "$KVER" "$m" >/dev/null 2>&1 || { echo "Modul nicht ladbar: $m"; fail=1; }
done
chroot "$R" /sbin/ip -j -4 addr >/dev/null 2>&1 || { echo "ip -j fehlt (iproute2)"; fail=1; }
[ -L "$R/etc/systemd/system/timers.target.wants/aroio-boot-report.timer" ] || [ "$(cat "$R/etc/aroio-version")" != "dev" ] \
    || { echo "Diagnosebericht fehlt im Entwicklungs-Image"; fail=1; }

mkdir -p "$R/tmp/f"
cat > "$R/tmp/gen.py" <<'PY'
import json, sys, numpy as np
sys.path.insert(0, "/usr/lib/aroiod")
from aroiod import dsp
from aroiod.config import builtin_bypass
t = np.zeros(4096); t[0] = 1
for ch in "LR":
    t.astype("<f8").tofile(f"/tmp/f/x_{ch}_96000.dbl")
peq = {"id": "p", "kind": "peq", "gain_db": -3, "trim_db": {"L": -1, "R": 0}, "delay_ms": {"L": 0, "R": 0.35},
       "peq": {"L": [{"type": "peaking", "freq": 43, "gain": -7, "q": 3}, {"type": "lowshelf", "freq": 120, "gain": 2, "q": 0.7},
                     {"type": "highpass", "freq": 20, "gain": 0, "q": 0.7}], "R": []}}
fir = {"id": "f", "kind": "fir", "fir": {"96000": {"L": "x_L_96000.dbl", "R": "x_R_96000.dbl"}}}
cases = {"bypass": dsp.camilla_config(builtin_bypass(), 44100),
         "cleaner": dsp.camilla_config(builtin_bypass(), 48000, ms_cleaner=True),
         "peq": dsp.camilla_config(peq, 96000, ms_cleaner=True),
         "resample": dsp.camilla_config(peq, 96000, capture_rate=44100, resampler="best"),
         "fir": dsp.camilla_config(fir, 96000, fir_dir="/tmp/f")}
for name, cfg in cases.items():
    json.dump(cfg, open(f"/tmp/{name}.json", "w"))
print(" ".join(cases))
PY
for c in $(chroot "$R" /usr/bin/python3 /tmp/gen.py); do
    # 4.1 may log a line after the verdict: look for it in the whole output
    out=$(chroot "$R" /usr/bin/camilladsp --check "/tmp/$c.json" 2>&1)
    if echo "$out" | grep -qx "Config is valid"; then printf 'camilladsp %-9s ok\n' "$c"
    else printf 'camilladsp %-9s %s\n' "$c" "$(echo "$out" | tail -3)"; fail=1; fi
done

# aroiod in real mode (no CamillaDSP running: it keeps retrying, the app must still work)
chroot "$R" /bin/sh -c 'cd /usr/lib/aroiod && exec /usr/bin/python3 -m aroiod --data /tmp/data --host 127.0.0.1 --port 8099 --static /usr/share/aroio-web' >/tmp/aroiod.log 2>&1 &
PID=$!
cat > "$R/tmp/probe.py" <<'PY'
import json, time, urllib.request
for _ in range(60):
    try:
        s = json.load(urllib.request.urlopen("http://127.0.0.1:8099/api/v1/state", timeout=1))
        html = urllib.request.urlopen("http://127.0.0.1:8099/einstellungen", timeout=1).read().decode()
        print("aroiod: Modell", s["device"]["model"], "| Board", s["device"]["board"], "| simuliert", s["device"]["simulated"],
              "| App", "ok" if "<div id=\"app\">" in html else "FEHLT")
        break
    except OSError:
        time.sleep(0.25)
else:
    raise SystemExit("aroiod antwortet nicht")
PY
chroot "$R" /usr/bin/python3 /tmp/probe.py || { fail=1; cat /tmp/aroiod.log; }
kill $PID 2>/dev/null || true
[ $fail = 0 ] && echo "Selbsttest: alles ok" || { echo "Selbsttest: FEHLER"; exit 1; }
