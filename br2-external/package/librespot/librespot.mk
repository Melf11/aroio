################################################################################
#
# librespot (Spotify Connect)
#
# 0.8.0 ships a Cargo.lock (Buildroot vendors it), needs Rust >= 1.85.
# ALSA output into the loopback, Spotify Connect discovery via the built-in
# mDNS responder, TLS via the system OpenSSL.
#
################################################################################

LIBRESPOT_VERSION = 0.8.0
LIBRESPOT_SITE = $(call github,librespot-org,librespot,v$(LIBRESPOT_VERSION))
LIBRESPOT_LICENSE = MIT
LIBRESPOT_LICENSE_FILES = LICENSE
LIBRESPOT_DEPENDENCIES = alsa-lib openssl host-pkgconf
LIBRESPOT_FEATURES = --no-default-features --features alsa-backend,with-libmdns,native-tls
LIBRESPOT_CARGO_BUILD_OPTS = $(LIBRESPOT_FEATURES)
LIBRESPOT_CARGO_INSTALL_OPTS = $(LIBRESPOT_FEATURES)
LIBRESPOT_CARGO_ENV = OPENSSL_NO_VENDOR=1

$(eval $(cargo-package))
