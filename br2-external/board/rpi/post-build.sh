#!/bin/sh
# Runs on the target directory before the root filesystem image is made.
set -e
TARGET="$1"
# read-only root: mutable state lives on /data
mkdir -p "$TARGET/data"
grep -q '/data' "$TARGET/etc/fstab" || echo 'LABEL=data /data ext4 defaults,noatime,commit=5 0 2' >> "$TARGET/etc/fstab"
# logs only in RAM
mkdir -p "$TARGET/etc/systemd/journald.conf.d"
printf '[Journal]\nStorage=volatile\nRuntimeMaxUse=16M\n' > "$TARGET/etc/systemd/journald.conf.d/aroio.conf"
# version shown in the app
echo "${AROIO_VERSION:-dev}" > "$TARGET/etc/aroio-version"
