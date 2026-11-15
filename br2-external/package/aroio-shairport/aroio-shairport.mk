################################################################################
#
# aroio-shairport: Shairport Sync 5.6 (AirPlay 2 receiver)
#
# 5.6 brings remote control of AirPlay 2 senders through its D-Bus interface
# (org.gnome.ShairportSync.RemoteControl): aroiod pauses/skips on the iPhone instead
# of ending the session. Output to the loopback (ALSA), metadata pipe for aroiod.
#
################################################################################

AROIO_SHAIRPORT_VERSION = 5.6.3
AROIO_SHAIRPORT_SITE = $(call github,mikebrady,shairport-sync,$(AROIO_SHAIRPORT_VERSION))
AROIO_SHAIRPORT_LICENSE = MIT, BSD-3-Clause
AROIO_SHAIRPORT_LICENSE_FILES = LICENSES
AROIO_SHAIRPORT_DEPENDENCIES = alsa-lib libconfig popt host-pkgconf avahi openssl libdaemon \
	libglib2 libplist libsodium libgcrypt ffmpeg util-linux host-vim
AROIO_SHAIRPORT_AUTORECONF = YES

AROIO_SHAIRPORT_CONF_OPTS = --with-alsa --with-metadata --with-pipe --with-stdout \
	--with-avahi --without-tinysvcmdns --with-ssl=openssl \
	--with-airplay-2 --with-dbus-interface --without-mpris-interface \
	--without-convolution --without-soxr --without-mqtt-client

ifeq ($(BR2_PACKAGE_LIBDAEMON),y)
AROIO_SHAIRPORT_CONF_OPTS += --with-libdaemon
else
AROIO_SHAIRPORT_DEPENDENCIES := $(filter-out libdaemon,$(AROIO_SHAIRPORT_DEPENDENCIES))
AROIO_SHAIRPORT_CONF_OPTS += --without-libdaemon
endif

define AROIO_SHAIRPORT_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/shairport-sync $(TARGET_DIR)/usr/bin/shairport-sync
	$(INSTALL) -D -m 0644 $(@D)/scripts/shairport-sync-dbus-policy.conf \
		$(TARGET_DIR)/usr/share/dbus-1/system.d/shairport-sync-dbus.conf
endef

$(eval $(autotools-package))
