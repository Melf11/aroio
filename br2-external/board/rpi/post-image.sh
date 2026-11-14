#!/bin/sh
# SD card image (+ RAUC bundle). AROIO_PROFILE=generic|iqaudio|aroio selects the DAC overlays.
set -e
BOARD_DIR="$(dirname "$0")"
PROFILE="${AROIO_PROFILE:-generic}"
cp "$BOARD_DIR/profiles/$PROFILE.txt" "$BINARIES_DIR/aroio.txt"
echo "DAC profile: $PROFILE"

GENIMAGE_TMP="${BUILD_DIR}/genimage.tmp"
rm -rf "$GENIMAGE_TMP"
genimage --rootpath "$TARGET_DIR" --tmppath "$GENIMAGE_TMP" --inputpath "$BINARIES_DIR" \
         --outputpath "$BINARIES_DIR" --config "$BOARD_DIR/genimage.cfg"

# RAUC bundle, signed with the release key from CI, otherwise with the development key
CERT="${AROIO_RAUC_CERT:-$BINARIES_DIR/rauc-dev/cert.pem}"
KEY="${AROIO_RAUC_KEY:-$BINARIES_DIR/rauc-dev/key.pem}"
if [ -f "$CERT" ] && [ -f "$KEY" ]; then
    BUNDLE="$BINARIES_DIR/bundle"
    rm -rf "$BUNDLE" "$BINARIES_DIR"/aroio-*.raucb
    mkdir -p "$BUNDLE"
    cp "$BINARIES_DIR/rootfs.squashfs" "$BUNDLE/"
    sed "s/@VERSION@/${AROIO_VERSION:-dev}/" "$BOARD_DIR/rauc/manifest.raucm" > "$BUNDLE/manifest.raucm"
    "$HOST_DIR/bin/rauc" bundle --cert="$CERT" --key="$KEY" "$BUNDLE" "$BINARIES_DIR/aroio-${AROIO_VERSION:-dev}.raucb"
fi
