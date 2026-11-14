################################################################################
#
# aroio-web: prebuilt PWA (web/dist). Node is not part of the image build.
#
################################################################################

AROIO_WEB_VERSION = local
AROIO_WEB_SITE = $(BR2_EXTERNAL_AROIO_PATH)/../web/dist
AROIO_WEB_SITE_METHOD = local
AROIO_WEB_LICENSE = proprietary

define AROIO_WEB_INSTALL_TARGET_CMDS
	test -f $(@D)/index.html || { echo "web/dist fehlt: zuerst 'make web'"; exit 1; }
	mkdir -p $(TARGET_DIR)/usr/share/aroio-web
	cp -a $(@D)/. $(TARGET_DIR)/usr/share/aroio-web/
	rm -f $(TARGET_DIR)/usr/share/aroio-web/sim.html $(TARGET_DIR)/usr/share/aroio-web/assets/sim-*
endef

$(eval $(generic-package))
