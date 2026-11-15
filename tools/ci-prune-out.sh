#!/bin/sh
# Shrinks an unfinished Buildroot output so CI can hand it over to the next run
# (GitHub-hosted jobs end after 6 h; the first build from scratch can take longer).
# Packages that are completely installed keep only their stamp files: Buildroot then
# skips them, their results are in host/, staging/ and target/ already.
# Exceptions: packages whose build directory the final steps still read (target-finalize
# and rootfs hooks: Python's compileall.py, BusyBox's .config, …) stay complete.
KEEP='busybox-* python3-* host-python3-* systemd-* host-systemd-* bash-* libglib2-* skeleton* linux-* nss-mdns-* ca-certificates-*' 
#   tools/ci-prune-out.sh /path/to/out
set -eu
OUT=${1:?Buildroot-Ausgabe}
freed=0
for d in "$OUT"/build/*/; do
    [ -e "$d.stamp_target_installed" ] || [ -e "$d.stamp_host_installed" ] || continue
    name=$(basename "$d"); keep=
    for k in $KEEP; do case "$name" in $k) keep=1;; esac; done
    [ -z "$keep" ] || continue
    before=$(du -sk "$d" | cut -f1)
    find "$d" -mindepth 1 -maxdepth 1 ! -name '.stamp_*' ! -name '.files-list*' ! -name '.br_*' -exec rm -rf {} +
    freed=$((freed + before - $(du -sk "$d" | cut -f1)))
done
echo "freigegeben: $((freed / 1024)) MB, übrig: $(du -sm "$OUT" | cut -f1) MB"
