################################################################################
#
# aroiod (from this repository)
#
################################################################################

AROIOD_VERSION = local
AROIOD_SITE = $(BR2_EXTERNAL_AROIO_PATH)/../aroiod
AROIOD_SITE_METHOD = local
AROIOD_LICENSE = proprietary

define AROIOD_INSTALL_TARGET_CMDS
	mkdir -p $(TARGET_DIR)/usr/lib/aroiod/aroiod
	cp -a $(@D)/*.py $(TARGET_DIR)/usr/lib/aroiod/aroiod/
	$(HOST_DIR)/bin/python3 -m compileall -q $(TARGET_DIR)/usr/lib/aroiod
endef

$(eval $(generic-package))
