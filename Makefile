# AroioOS. Everyday development: ./dev.sh (simulator). This Makefile ties the parts together.
#
#   make test          backend tests, svelte-check, build, i18n
#   make e2e           Playwright: flows + accessibility (axe, WCAG 2.2 AA), mobile + desktop
#   make web           build the app into web/dist
#   make docker-image  SD card image, built in Docker (macOS/Linux). Result: output/aroio-sdcard.img
#   make image         same without Docker (Linux host with a case-sensitive file system)
#
# Options: AROIO_PROFILE=generic|iqaudio|aroio (DAC overlays, see br2-external/board/rpi/profiles)
#          AROIO_VERSION=x.y.z

BR_VERSION ?= 2026.02.3
BR_DIR ?= $(CURDIR)/buildroot
OUT ?= $(CURDIR)/output/build
BR2_DL_DIR ?= $(CURDIR)/output/dl
COPY_TO ?= $(CURDIR)/output
AROIO_PROFILE ?= aroio
AROIO_VERSION ?= dev
# development images only: your public SSH key for root login (never in release builds)
AROIO_SSH_PUBKEY ?= $(if $(filter dev,$(AROIO_VERSION)),$(shell cat $(HOME)/.ssh/id_ed25519.pub $(HOME)/.ssh/id_rsa.pub 2>/dev/null | head -1))
export BR2_DL_DIR AROIO_PROFILE AROIO_VERSION AROIO_SSH_PUBKEY

.PHONY: test e2e web buildroot image docker-image

test:
	./dev.sh test

e2e: web
	cd web && npx playwright test

web:
	cd web && npm ci --no-audit --no-fund && npx vite build

buildroot:
	test -d $(BR_DIR) || git clone --depth 1 --branch $(BR_VERSION) https://gitlab.com/buildroot.org/buildroot.git $(BR_DIR)

image: buildroot
	test -f web/dist/index.html || { echo "web/dist fehlt: zuerst 'make web'"; exit 1; }
	$(MAKE) -C $(BR_DIR) BR2_EXTERNAL=$(CURDIR)/br2-external O=$(OUT) aroio_rpi_defconfig
	$(MAKE) -C $(OUT) host-rust-bin
	HOST_DIR=$(OUT)/host tools/vendor-camilladsp.sh
	# package list with licenses for the app (aroiod.mk turns it into licenses.json)
	$(MAKE) -s -C $(OUT) show-info > $(OUT)/show-info.json
	# our own packages and the boot files (config.txt, cmdline.txt) come from this repository: fresh on every build
	$(MAKE) -C $(OUT) aroiod-dirclean aroio-web-dirclean rpi-firmware-dirclean
	$(MAKE) -C $(OUT)
	mkdir -p $(COPY_TO)
	cp $(OUT)/images/sdcard.img $(COPY_TO)/aroio-sdcard.img
	# download size: xz shrinks the empty space in the partitions to almost nothing
	xz -T0 -6 -k -f $(COPY_TO)/aroio-sdcard.img
	cp $(OUT)/images/aroio-*.raucb $(COPY_TO)/ 2>/dev/null || true
	@echo "Fertig: $(COPY_TO)/aroio-sdcard.img"

# Buildroot output lives in a Docker volume: macOS file systems are case-insensitive,
# which breaks the kernel build, and bind mounts are slow.
docker-image: web
	docker build -t aroio-build docker
	docker run --rm -v $(CURDIR):/work -v aroio-build:/build -w /work \
		-e AROIO_PROFILE=$(AROIO_PROFILE) -e AROIO_VERSION=$(AROIO_VERSION) -e AROIO_SSH_PUBKEY="$(AROIO_SSH_PUBKEY)" aroio-build \
		make image BR_DIR=/build/buildroot OUT=/build/out BR2_DL_DIR=/build/dl COPY_TO=/work/output
