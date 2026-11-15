#!/bin/sh
# Shrinks an unfinished Buildroot output so CI can hand it over to the next run
# (GitHub-hosted jobs end after 6 h; the first build from scratch can take longer).
# Packages that are completely installed keep only their stamp files: Buildroot then
# skips them, their results are in host/, staging/ and target/ already.
#   tools/ci-prune-out.sh /path/to/out
set -eu
OUT=${1:?Buildroot-Ausgabe}
freed=0
for d in "$OUT"/build/*/; do
    [ -e "$d.stamp_target_installed" ] || [ -e "$d.stamp_host_installed" ] || continue
    before=$(du -sk "$d" | cut -f1)
    find "$d" -mindepth 1 -maxdepth 1 ! -name '.stamp_*' ! -name '.files-list*' ! -name '.br_*' -exec rm -rf {} +
    freed=$((freed + before - $(du -sk "$d" | cut -f1)))
done
echo "freigegeben: $((freed / 1024)) MB, übrig: $(du -sm "$OUT" | cut -f1) MB"
