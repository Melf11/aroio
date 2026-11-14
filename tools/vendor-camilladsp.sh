#!/bin/sh
# Builds the vendored CamillaDSP source archive Buildroot expects in its download
# directory (upstream has no Cargo.lock). Runs in the build container.
#   HOST_DIR=<buildroot output>/host BR2_DL_DIR=<dl> tools/vendor-camilladsp.sh
# The first run creates br2-external/package/camilladsp/Cargo.lock: commit it,
# later runs reuse it, so builds are reproducible.
set -eu
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$REPO/br2-external/package/camilladsp"
VER=$(sed -n 's/^CAMILLADSP_VERSION = //p' "$PKG/camilladsp.mk")
OUT="${BR2_DL_DIR:?}/camilladsp/camilladsp-$VER-cargo4.tar.gz"
CARGO="${HOST_DIR:?}/bin/cargo"
LOCK="$PKG/Cargo.lock.$VER"

if [ -f "$OUT" ] && [ -f "$LOCK" ]; then
    echo "camilladsp $VER: vendored archive present"
    exit 0
fi
mkdir -p "$(dirname "$OUT")"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CARGO_HOME="$TMP/cargo-home" PATH="$HOST_DIR/bin:$PATH"
wget -q -O "$TMP/src.tar.gz" "https://github.com/HEnquist/camilladsp/archive/refs/tags/v$VER.tar.gz"
tar xzf "$TMP/src.tar.gz" -C "$TMP"
cd "$TMP/camilladsp-$VER"
if [ -f "$LOCK" ]; then
    cp "$LOCK" Cargo.lock
else
    "$CARGO" generate-lockfile
    cp Cargo.lock "$LOCK"
    echo "camilladsp $VER: new lockfile $LOCK (please commit)"
fi
mkdir -p .cargo
"$CARGO" vendor --locked VENDOR > .cargo/config.toml
cd "$TMP"
tar czf "$OUT" --owner=0 --group=0 --numeric-owner --mtime=@0 --sort=name "camilladsp-$VER"
echo "camilladsp $VER: $OUT"
