################################################################################
#
# camilladsp
#
# Upstream does not ship a Cargo.lock, so Buildroot's `cargo vendor --locked`
# cannot vendor it. tools/vendor-camilladsp.sh builds the vendored archive from
# the upstream release and the Cargo.lock kept next to this file; the Makefile
# runs it before the build. 4.1 needs Rust >= 1.90 (Buildroot 2026.08: 1.97) and
# brings NEON-accelerated FFT convolution on aarch64 (room correction filters).
#
################################################################################

CAMILLADSP_VERSION = 4.1.3
CAMILLADSP_SITE = $(call github,HEnquist,camilladsp,v$(CAMILLADSP_VERSION))
CAMILLADSP_LICENSE = GPL-3.0-only or MPL-2.0
CAMILLADSP_DEPENDENCIES = alsa-lib

$(eval $(cargo-package))
