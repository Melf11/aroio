#!/bin/sh
# SD card image (+ RAUC bundle). AROIO_PROFILE=generic|iqaudio|aroio selects the DAC overlays.
set -e
BOARD_DIR="$(dirname "$0")"
PROFILE="${AROIO_PROFILE:-generic}"
cp "$BOARD_DIR/profiles/$PROFILE.txt" "$BINARIES_DIR/aroio.txt"
echo "DAC profile: $PROFILE"

# slot A of the SD card image: the boot files from the root file system (see post-build.sh)
rm -rf "$BINARIES_DIR/slot-a"
cp -r "$TARGET_DIR/usr/share/aroio/boot" "$BINARIES_DIR/slot-a"
sed 's|@ROOT@|/dev/mmcblk0p2|; s|@SLOT@|A|' "$BINARIES_DIR/slot-a/cmdline.txt.in" > "$BINARIES_DIR/slot-a/cmdline.txt"
rm "$BINARIES_DIR/slot-a/cmdline.txt.in"

GENIMAGE_TMP="${BUILD_DIR}/genimage.tmp"
rm -rf "$GENIMAGE_TMP"
genimage --rootpath "$TARGET_DIR" --tmppath "$GENIMAGE_TMP" --inputpath "$BINARIES_DIR" \
         --outputpath "$BINARIES_DIR" --config "$BOARD_DIR/genimage.cfg"

# further SD card images that differ only in aroio.txt (releases: one per DAC profile)
for p in ${AROIO_PROFILES:-}; do
    cp "$BOARD_DIR/profiles/$p.txt" "$BINARIES_DIR/aroio.txt"
    OUT_P="$BUILD_DIR/genimage.$p"
    rm -rf "$GENIMAGE_TMP" "$OUT_P"
    mkdir -p "$OUT_P"
    genimage --rootpath "$TARGET_DIR" --tmppath "$GENIMAGE_TMP" --inputpath "$BINARIES_DIR" \
             --outputpath "$OUT_P" --config "$BOARD_DIR/genimage.cfg"
    mv "$OUT_P/sdcard.img" "$BINARIES_DIR/sdcard-$p.img"
    rm -rf "$OUT_P"
    echo "SD card image for profile $p"
done
cp "$BOARD_DIR/profiles/$PROFILE.txt" "$BINARIES_DIR/aroio.txt"

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
