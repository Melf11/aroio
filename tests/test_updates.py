"""Updates from GitHub releases, NetJack controller, A/B boot scripts."""

import subprocess
from pathlib import Path

from aroiod import netjack, updates

ROOT = Path(__file__).resolve().parent.parent


def rel(tag, pre=False, draft=False, bundle=True, body="- Neu: NetJack\n- [Fehler](http://x) behoben\nText"):
    assets = [{"name": f"aroio-{tag.lstrip('v')}.raucb", "browser_download_url": f"https://x/{tag}.raucb", "size": 10}]
    return {"tag_name": tag, "prerelease": pre, "draft": draft, "body": body,
            "assets": assets if bundle else [], "html_url": f"https://x/{tag}"}


def test_versions():
    assert updates.newer("0.2.0", "0.1.9") and not updates.newer("0.1.0", "0.1.0")
    assert updates.newer("1.0.0", "1.0.0-beta.2") and updates.newer("1.0.0-beta.10", "1.0.0-beta.2")
    assert updates.newer("0.0.1", "dev") and updates.newer("0.1.0", "0.1.0-dev")
    assert updates.is_release("1.2.3") and updates.is_release("1.2.3-beta.1")
    assert not updates.is_release("dev") and not updates.is_release("0.1.0-dev")


def test_pick_release_by_channel():
    releases = [rel("v0.3.0-beta.1", pre=True), rel("v0.2.0"), rel("v0.4.0", draft=True), rel("v0.5.0", bundle=False)]
    stable = updates.pick_release(releases, "stable", "0.1.0")
    assert stable["version"] == "0.2.0" and stable["url"].endswith("v0.2.0.raucb")
    assert stable["notes"] == ["Neu: NetJack", "Fehler behoben"]
    assert updates.pick_release(releases, "beta", "0.1.0")["version"] == "0.3.0-beta.1"
    assert updates.pick_release(releases, "stable", "0.2.0") is None



def test_beta_install_follows_betas_on_stable_channel():
    """0.2.0-beta.1 with the default channel "stable" found nothing while only betas existed."""
    releases = [rel("v0.2.0-beta.2", pre=True), rel("v0.2.0-beta.1", pre=True)]
    assert updates.pick_release(releases, "stable", "0.2.0-beta.1")["version"] == "0.2.0-beta.2"
    assert updates.pick_release(releases, "stable", "0.1.0") is None
    assert updates.pick_release(releases, "stable", "0.1.0-dev") is None


def test_auto_install_only_at_night_and_on_releases():
    assert updates.auto_install_due(3, False, True, "1.0.0")
    assert not updates.auto_install_due(12, False, True, "1.0.0")
    assert not updates.auto_install_due(3, True, True, "1.0.0")
    assert not updates.auto_install_due(3, False, False, "1.0.0")
    assert not updates.auto_install_due(3, False, True, "dev")
    assert updates.rauc_progress("  40% Copying image to rootfs.1") == 40
    assert updates.rauc_progress("installing") is None


class FakeJack:
    def __init__(self):
        self.out, self.loaded, self.links, self.n = [], {}, [], 0

    def ports(self, pattern, flags=0):
        return [p for p in self.out if pattern in p]

    def load(self, name, so, init=""):
        self.n += 1
        self.loaded[self.n] = (name, so, init)
        return self.n

    def unload(self, h):
        del self.loaded[h]

    def connect(self, a, b):
        self.links.append((a, b))
        return True


def test_netjack_opens_loopback_only_while_a_computer_is_connected():
    jack, events = FakeJack(), []
    ctl = netjack.Controller(jack, events.append, "-P plughw:Loopback,0,0")
    ctl.tick()
    assert not jack.loaded and not events
    jack.out = ["studio:from_slave_2", "studio:from_slave_1"]
    ctl.tick()
    assert [v[1] for v in jack.loaded.values()] == ["audioadapter"]
    assert jack.links == [("studio:from_slave_1", "aroio-out:playback_1"), ("studio:from_slave_2", "aroio-out:playback_2")]
    assert events[-1]["event"] == "start" and events[-1]["meta"]["artist"] == "studio"
    ctl.pause()                                   # another source plays: let go, do not come back
    assert not jack.loaded
    ctl.tick()
    assert not jack.loaded and len(events) == 1
    jack.out = []                                 # computer disconnects ...
    ctl.tick()
    jack.out = ["studio:from_slave_1"]            # ... and comes back: plays again (mono on both sides)
    ctl.tick()
    assert jack.loaded and ("studio:from_slave_1", "aroio-out:playback_2") in jack.links
    jack.out = []
    ctl.tick()
    assert not jack.loaded and events[-1] == {"source": "netjack", "event": "stop"}


def test_netjack_source_and_migration(device):
    from aroiod.migration import migrate
    assert device.config.get("sources.netjack") == {"enabled": False, "rate": 48000}
    device.patch_config({"sources": {"netjack": {"enabled": True, "rate": 96000}}})
    assert any(s["id"] == "netjack" and s["enabled"] for s in device.hub.topics["sources"])
    assert device.hub.topics["services"]["netjack"] == {"enabled": True, "rate": 96000}
    r = migrate('AUDIO_OUTPUT="jack"\nJACK_NETJACK="ON"\n')
    assert r["patch"]["sources"]["netjack"]["enabled"] is True


def _run(script, *args, env=None):
    return subprocess.run(["sh", str(ROOT / script), *args], capture_output=True, text=True, env=env)


def test_boot_scripts_are_valid_shell():
    for f in ("rauc-tryboot", "reboot", "mark-good", "trial-watch", "aroio-python"):
        r = subprocess.run(["sh", "-n", str(ROOT / "br2-external/board/rpi/overlay/usr/lib/aroio" / f)],
                           capture_output=True, text=True)
        assert r.returncode == 0, (f, r.stderr)
    cfg = (ROOT / "br2-external/board/rpi/config.txt").read_text()
    assert "\nos_prefix=slot-a/\n" in cfg
    cmd = (ROOT / "br2-external/board/rpi/cmdline.txt").read_text()
    assert "root=@ROOT@" in cmd and "rauc.slot=@SLOT@" in cmd
    assert "BEGIN CERTIFICATE" in (ROOT / "br2-external/board/rpi/rauc/release-cert.pem").read_text()


def _tryboot(tmp, model, booted):
    env = {"PATH": "/usr/bin:/bin", "AROIO_BOOT": str(tmp / "boot"), "AROIO_STATE": str(tmp / "state"),
           "AROIO_RUN": str(tmp / "run"), "AROIO_CMDLINE": str(tmp / "cmdline"),
           "AROIO_MODEL_FILE": str(tmp / "model"), "AROIO_TEST_ROOTS": str(tmp / "roots")}
    (tmp / "model").write_text(model)
    (tmp / "cmdline").write_text(f"root=/dev/mmcblk0p{2 if booted == 'A' else 3} rauc.slot={booted} ro\n")

    def run(*args):
        r = _run("br2-external/board/rpi/overlay/usr/lib/aroio/rauc-tryboot", *args, env=env)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()
    return run


def _sd_card(tmp):
    boot = tmp / "boot"
    (boot / "slot-a").mkdir(parents=True)
    (boot / "config.txt").write_text("[all]\nos_prefix=slot-a/\nkernel=Image\ninclude aroio.txt\n")
    new = tmp / "roots" / "B" / "usr/share/aroio/boot"
    (new / "overlays").mkdir(parents=True)
    (new / "Image").write_text("kernel 2")
    (new / "overlays" / "x.dtbo").write_text("o")
    (new / "cmdline.txt.in").write_text("root=@ROOT@ rauc.slot=@SLOT@ ro\n")
    return boot


def test_ab_update_pi4_tryboot_then_good(tmp_path):
    boot = _sd_card(tmp_path)
    rt = _tryboot(tmp_path, "Raspberry Pi 4 Model B Rev 1.5", "A")
    assert rt("get-primary") == "A" and rt("get-current") == "A"
    rt("set-primary", "B")                                       # after `rauc install`
    assert (boot / "slot-b/Image").read_text() == "kernel 2"
    assert (boot / "slot-b/cmdline.txt").read_text() == "root=/dev/mmcblk0p3 rauc.slot=B ro\n"
    assert not (boot / "slot-b/cmdline.txt.in").exists()
    assert "os_prefix=slot-b/" in (boot / "tryboot.txt").read_text()
    assert rt("get-primary") == "A"                              # config.txt untouched: a failed try goes back
    assert (tmp_path / "run/tryboot").exists()
    rt = _tryboot(tmp_path, "Raspberry Pi 4 Model B Rev 1.5", "B")   # tryboot into B, aroiod up
    rt("set-state", "B", "good")
    assert rt("get-primary") == "B" and not (boot / "tryboot.txt").exists()
    assert "include aroio.txt" in (boot / "config.txt").read_text()


def test_ab_update_pi3_reverts_when_unhealthy(tmp_path):
    boot = _sd_card(tmp_path)
    rt = _tryboot(tmp_path, "Raspberry Pi 3 Model B Plus Rev 1.3", "A")
    rt("set-primary", "B")
    assert rt("get-primary") == "B" and not (boot / "tryboot.txt").exists()   # no tryboot on a Pi 3
    rt = _tryboot(tmp_path, "Raspberry Pi 3 Model B Plus Rev 1.3", "B")
    rt("revert")                                                  # aroio-trial-watch: B never got healthy
    assert rt("get-primary") == "A" and rt("get-state", "B") == "bad"
