################################################################################
#
# font-inter: the typeface of the HDMI info screen (three static weights)
#
################################################################################

FONT_INTER_VERSION = 4.1
FONT_INTER_SOURCE = Inter-$(FONT_INTER_VERSION).zip
FONT_INTER_SITE = https://github.com/rsms/inter/releases/download/v$(FONT_INTER_VERSION)
FONT_INTER_LICENSE = OFL-1.1
FONT_INTER_LICENSE_FILES = LICENSE.txt

define FONT_INTER_EXTRACT_CMDS
	$(UNZIP) -q -o $(FONT_INTER_DL_DIR)/$(FONT_INTER_SOURCE) LICENSE.txt \
		'extras/ttf/Inter-Regular.ttf' 'extras/ttf/Inter-SemiBold.ttf' 'extras/ttf/Inter-Bold.ttf' -d $(@D)
endef

define FONT_INTER_INSTALL_TARGET_CMDS
	mkdir -p $(TARGET_DIR)/usr/share/fonts/inter
	$(INSTALL) -m 0644 $(@D)/extras/ttf/Inter-Regular.ttf $(@D)/extras/ttf/Inter-SemiBold.ttf \
		$(@D)/extras/ttf/Inter-Bold.ttf $(TARGET_DIR)/usr/share/fonts/inter/
endef

$(eval $(generic-package))
