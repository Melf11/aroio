################################################################################
#
# camilladsp
#
################################################################################

CAMILLADSP_VERSION = 3.0.1
CAMILLADSP_SITE = $(call github,HEnquist,camilladsp,v$(CAMILLADSP_VERSION))
CAMILLADSP_LICENSE = GPL-3.0
CAMILLADSP_LICENSE_FILES = LICENSE.txt
CAMILLADSP_DEPENDENCIES = alsa-lib
CAMILLADSP_CARGO_BUILD_OPTS = --no-default-features --features websocket

$(eval $(cargo-package))
