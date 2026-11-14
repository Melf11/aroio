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
	# ABACUS factory filters (BBC-Dip, Echo; from AroioOS 5.1), unpacked, read-only;
	# the right channels are symlinks to the left ones in the archive (-h follows them)
	rm -rf $(TARGET_DIR)/usr/share/aroio/filters $(@D)/factory-tmp
	mkdir -p $(TARGET_DIR)/usr/share/aroio/filters $(@D)/factory-tmp
	tar xzf $(@D)/factory/filter.tgz -C $(@D)/factory-tmp
	for f in $(@D)/factory-tmp/filter/BBCDip*.dbl $(@D)/factory-tmp/filter/Echo*.dbl; do \
		cp -L $$f $(TARGET_DIR)/usr/share/aroio/filters/; done
	# licenses of all packages (Buildroot show-info, written by the Makefile) for the app
	if [ -f $(BASE_DIR)/show-info.json ]; then \
		$(HOST_DIR)/bin/python3 $(BR2_EXTERNAL_AROIO_PATH)/../tools/licenses-json.py \
			$(BASE_DIR)/show-info.json > $(TARGET_DIR)/usr/share/aroio/licenses.json; fi
endef

$(eval $(generic-package))
