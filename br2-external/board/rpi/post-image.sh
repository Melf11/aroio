#!/bin/sh
# Builds the SD card image and the RAUC update bundle.
set -e
BOARD_DIR="$(dirname "$0")"
GENIMAGE_TMP="${BUILD_DIR}/genimage.tmp"
rm -rf "$GENIMAGE_TMP"
genimage --rootpath "$TARGET_DIR" --tmppath "$GENIMAGE_TMP" --inputpath "$BINARIES_DIR" \
         --outputpath "$BINARIES_DIR" --config "$BOARD_DIR/genimage.cfg"
# RAUC bundle (signing key from CI secrets, never in the repo)
if [ -n "${AROIO_RAUC_KEY:-}" ]; then
    mkdir -p "$BINARIES_DIR/bundle"
    cp "$BINARIES_DIR/rootfs.squashfs" "$BINARIES_DIR/bundle/"
    sed "s/@VERSION@/${AROIO_VERSION:-dev}/" "$BOARD_DIR/rauc/manifest.raucm" > "$BINARIES_DIR/bundle/manifest.raucm"
    rauc bundle --cert="$AROIO_RAUC_CERT" --key="$AROIO_RAUC_KEY" "$BINARIES_DIR/bundle" "$BINARIES_DIR/aroio-${AROIO_VERSION:-dev}.raucb"
fi
