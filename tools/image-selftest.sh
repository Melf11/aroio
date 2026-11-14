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
for f in usr/bin/camilladsp usr/bin/squeezelite usr/bin/shairport-sync usr/bin/upmpdcli usr/bin/bluealsa \
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
         etc/systemd/system/multi-user.target.wants/aroio-bt-agent.service; do
    if [ -L "$R/$f" ]; then target="$R$(readlink "$R/$f")"; else target="$R/$f"; fi   # links are absolute
    [ -e "$target" ] || { echo "FEHLT: $f"; fail=1; }
done
[ -z "$(ls "$R/usr/share/aroio-web/assets" | grep sim || true)" ] || { echo "Simulator im Image"; fail=1; }
grep -q "^/dev/root / auto ro" "$R/etc/fstab" || { echo "Root nicht read-only in fstab"; fail=1; }
ls "$R"/usr/lib/firmware/brcm/BCM4345C0*.hcd >/dev/null 2>&1 || { echo "Bluetooth-Firmware Pi 4 (BCM4345C0) fehlt"; fail=1; }
grep -q "^root:[*!]" "$R/etc/shadow" || { echo "root hat ein leeres Passwort (dropbear lehnt dann auch Schlüssel ab)"; fail=1; }
if [ "$(cat "$R/etc/aroio-version")" = "dev" ]; then
    [ -s "$R/root/.ssh/authorized_keys" ] || { echo "SSH-Schlüssel fehlt im Entwicklungs-Image"; fail=1; }
fi
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
    out=$(chroot "$R" /usr/bin/camilladsp --check "/tmp/$c.json" 2>&1 | tail -1)
    printf 'camilladsp %-9s %s\n' "$c" "$out"
    [ "$out" = "Config is valid" ] || fail=1
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
