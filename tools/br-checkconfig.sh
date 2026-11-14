#!/bin/sh
make -s -C /build/buildroot BR2_EXTERNAL=/work/br2-external O=/build/out aroio_rpi_defconfig >/dev/null 2>&1
echo "--- nicht übernommen:"
grep -E "^BR2_[A-Z0-9_]+=" /work/br2-external/configs/aroio_rpi_defconfig | while IFS== read k v; do
  grep -q "^$k=" /build/out/.config || echo "  $k=$v"
done
