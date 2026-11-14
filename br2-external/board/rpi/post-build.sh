#!/bin/sh
# Runs on the target directory before the root filesystem image is made.
set -e
TARGET="$1"
BOARD_DIR="$(dirname "$0")"
# read-only root: mutable state lives on /data
mkdir -p "$TARGET/data"
grep -q 'LABEL=data' "$TARGET/etc/fstab" || echo 'LABEL=data /data ext4 defaults,noatime,commit=5 0 2' >> "$TARGET/etc/fstab"
# logs only in RAM
mkdir -p "$TARGET/etc/systemd/journald.conf.d"
printf '[Journal]\nStorage=volatile\nRuntimeMaxUse=16M\n' > "$TARGET/etc/systemd/journald.conf.d/aroio.conf"
echo "${AROIO_VERSION:-dev}" > "$TARGET/etc/aroio-version"

# development images: SSH login as root with the developer's public key (no passwords)
rm -f "$TARGET/root/.ssh/authorized_keys"
if [ "${AROIO_VERSION:-dev}" = "dev" ] && [ -n "${AROIO_SSH_PUBKEY:-}" ]; then
    mkdir -p "$TARGET/root/.ssh"
    chmod 700 "$TARGET/root/.ssh"
    printf '%s\n' "$AROIO_SSH_PUBKEY" > "$TARGET/root/.ssh/authorized_keys"
    chmod 600 "$TARGET/root/.ssh/authorized_keys"
    echo "SSH: developer key installed (dev image)"
fi

# not needed and slows down the boot by up to 2 minutes without network
ln -sf /dev/null "$TARGET/etc/systemd/system/systemd-networkd-wait-online.service"
mkdir -p "$TARGET/var/lib/mpd"   # Buildroot moves /var to /usr/share/factory/var (read-only root)

# services that start at boot
mkdir -p "$TARGET/etc/systemd/system/multi-user.target.wants"
while read -r unit; do
    [ -n "$unit" ] && ln -sf "/usr/lib/systemd/system/$unit" "$TARGET/etc/systemd/system/multi-user.target.wants/$unit"
done < "$BOARD_DIR/post-build-enable.txt"

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
cp "${AROIO_RAUC_CERT:-$DEV/cert.pem}" "$TARGET/etc/rauc/keyring.pem"
