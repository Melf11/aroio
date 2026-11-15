################################################################################
#
# aroio-nqptp: NQPTP matching Shairport Sync 5.6 (Buildroot has 1.2.4)
#
################################################################################

AROIO_NQPTP_VERSION = 1.2.9
AROIO_NQPTP_SITE = $(call github,mikebrady,nqptp,$(AROIO_NQPTP_VERSION))
AROIO_NQPTP_LICENSE = GPL-2.0
AROIO_NQPTP_LICENSE_FILES = LICENSE
AROIO_NQPTP_DEPENDENCIES = libconfig host-pkgconf
AROIO_NQPTP_AUTORECONF = YES

define AROIO_NQPTP_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/nqptp $(TARGET_DIR)/usr/bin/nqptp
endef

$(eval $(autotools-package))
