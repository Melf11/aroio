#!/bin/sh
# SD card image (+ RAUC bundle). One image for every device: the setup guide in the app
# writes aroio.txt (DAC driver, controls); the image starts with the neutral one.
set -e
BOARD_DIR="$(dirname "$0")"
cp "$BOARD_DIR/aroio.txt" "$BINARIES_DIR/aroio.txt"

# slot A of the SD card image: the boot files from the root file system (see post-build.sh)
rm -rf "$BINARIES_DIR/slot-a"
cp -r "$TARGET_DIR/usr/share/aroio/boot" "$BINARIES_DIR/slot-a"
sed 's|@ROOT@|/dev/mmcblk0p2|; s|@SLOT@|A|' "$BINARIES_DIR/slot-a/cmdline.txt.in" > "$BINARIES_DIR/slot-a/cmdline.txt"
rm "$BINARIES_DIR/slot-a/cmdline.txt.in"

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
