#!/bin/sh
# Runs on the target directory before the root filesystem image is made.
set -e
TARGET="$1"
BOARD_DIR="$(dirname "$0")"
# read-only root: mutable state lives on /data
mkdir -p "$TARGET/data"
# x-systemd.growfs: the file system follows when aroio-grow-data enlarged the partition
sed -i '/LABEL=data/d' "$TARGET/etc/fstab"
echo 'LABEL=data /data ext4 defaults,noatime,commit=5,x-systemd.growfs 0 2' >> "$TARGET/etc/fstab"
# logs only in RAM
mkdir -p "$TARGET/etc/systemd/journald.conf.d"
printf '[Journal]\nStorage=volatile\nRuntimeMaxUse=16M\n' > "$TARGET/etc/systemd/journald.conf.d/aroio.conf"
echo "${AROIO_VERSION:-dev}" > "$TARGET/etc/aroio-version"

# SSH host keys on the data partition: the same key across reboots and updates
# (Buildroot points /etc/dropbear to /var/run, a new key on every boot)
ln -snf /data/dropbear "$TARGET/etc/dropbear"

# development images: SSH login as root with the developer's public key (no passwords)
rm -f "$TARGET/root/.ssh/authorized_keys"
if [ "${AROIO_VERSION:-dev}" = "dev" ] && [ -n "${AROIO_SSH_PUBKEY:-}" ]; then
    mkdir -p "$TARGET/root/.ssh"
    chmod 700 "$TARGET/root/.ssh"
    printf '%s\n' "$AROIO_SSH_PUBKEY" > "$TARGET/root/.ssh/authorized_keys"
    chmod 600 "$TARGET/root/.ssh/authorized_keys"
    echo "SSH: developer key installed (dev image)"
fi

# development images: diagnosis report on the boot partition 90 s after boot (readable without network)
rm -f "$TARGET/etc/systemd/system/timers.target.wants/aroio-boot-report.timer"
if [ "${AROIO_VERSION:-dev}" = "dev" ]; then
    mkdir -p "$TARGET/etc/systemd/system/timers.target.wants"
    ln -sf /usr/lib/systemd/system/aroio-boot-report.timer "$TARGET/etc/systemd/system/timers.target.wants/aroio-boot-report.timer"
fi

# not needed and slows down the boot by up to 2 minutes without network
ln -sf /dev/null "$TARGET/etc/systemd/system/systemd-networkd-wait-online.service"
# iwd and bluetoothd keep their state on /data via systemd BindPaths (see *.service.d/aroio.conf)
rm -rf "$TARGET/var/lib/iwd"
mkdir -p "$TARGET/var/lib/mpd"   # Buildroot moves /var to /usr/share/factory/var (read-only root)

# services that start at boot
mkdir -p "$TARGET/etc/systemd/system/multi-user.target.wants"
while read -r unit; do
    [ -n "$unit" ] && ln -sf "/usr/lib/systemd/system/$unit" "$TARGET/etc/systemd/system/multi-user.target.wants/$unit"
done < "$BOARD_DIR/post-build-enable.txt"
mkdir -p "$TARGET/etc/systemd/system/data.mount.wants"
ln -sf /usr/lib/systemd/system/aroio-grow-data.service "$TARGET/etc/systemd/system/data.mount.wants/aroio-grow-data.service"

# Boot files of this system inside its root file system: an update copies them to its
# slot directory on the boot partition (rauc-tryboot), so the kernel is updated with the system.
BOOTFILES="$TARGET/usr/share/aroio/boot"
rm -rf "$BOOTFILES"
mkdir -p "$BOOTFILES"
cp "$BINARIES_DIR/Image" "$BOOTFILES/"
for dtb in bcm2710-rpi-3-b bcm2710-rpi-3-b-plus bcm2710-rpi-2-b bcm2711-rpi-4-b bcm2711-rpi-400 bcm2711-rpi-cm4 \
           bcm2712-rpi-5-b bcm2712-rpi-cm5-cm5io bcm2712d0-rpi-5-b; do
    [ -f "$BINARIES_DIR/$dtb.dtb" ] && cp "$BINARIES_DIR/$dtb.dtb" "$BOOTFILES/"
done
cp -r "$BINARIES_DIR/rpi-firmware/overlays" "$BOOTFILES/"
cp "$BINARIES_DIR/rpi-firmware/cmdline.txt" "$BOOTFILES/cmdline.txt.in"

# RAUC: system.conf + keyring. Without a release certificate a development key is created
# (only for development images; release builds pass AROIO_RAUC_CERT/AROIO_RAUC_KEY).
cp "$BOARD_DIR/rauc/system.conf" "$TARGET/etc/rauc/system.conf"
DEV="$BINARIES_DIR/rauc-dev"
if [ -z "${AROIO_RAUC_CERT:-}" ] && [ ! -f "$DEV/cert.pem" ]; then
    mkdir -p "$DEV"
    OPENSSL="$HOST_DIR/bin/openssl"; [ -x "$OPENSSL" ] || OPENSSL=openssl
    "$OPENSSL" req -x509 -newkey rsa:4096 -nodes -days 3650 -subj "/CN=AroioOS development" \
        -keyout "$DEV/key.pem" -out "$DEV/cert.pem" 2>/dev/null
fi
# Every image trusts the release certificate (updates from GitHub); development images
# also trust their own development key (bundles from ./dev.sh deploy --bundle).
cp "$BOARD_DIR/rauc/release-cert.pem" "$TARGET/etc/rauc/keyring.pem"
if [ -z "${AROIO_RAUC_CERT:-}" ]; then
    cat "$DEV/cert.pem" >> "$TARGET/etc/rauc/keyring.pem"
fi
