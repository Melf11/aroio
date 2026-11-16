# AroioOS. Everyday development: ./dev.sh (simulator). This Makefile ties the parts together.
#
#   make test          backend tests, svelte-check, build, i18n
#   make e2e           Playwright: flows + accessibility (axe, WCAG 2.2 AA), mobile + desktop
#   make web           build the app into web/dist
#   make docker-image  SD card image, built in Docker (macOS/Linux). Result: output/aroio-sdcard.img
#   make image         same without Docker (Linux host with a case-sensitive file system)
#
# Options: AROIO_VERSION=x.y.z               release builds (tag v x.y.z), "dev" otherwise
#          AROIO_RAUC_KEY=/path/key.pem      release signing key (CI); the certificate is in the repo
#          AROIO_BUILD_VOLUME=aroio-build    Docker volume or absolute host directory for the Buildroot output

BR_VERSION ?= 2026.11-rc1
BR_DIR ?= $(CURDIR)/buildroot
OUT ?= $(CURDIR)/output/build
BR2_DL_DIR ?= $(CURDIR)/output/dl
COPY_TO ?= $(CURDIR)/output
AROIO_VERSION ?= dev
AROIO_BUILD_VOLUME ?= aroio-build
AROIO_RAUC_KEY ?=
# name of the build container (CI stops it by name when a run has to hand over)
AROIO_CONTAINER ?= aroio-build-run
# development images only: your public SSH key for root login (never in release builds)
AROIO_SSH_PUBKEY ?= $(if $(filter dev,$(AROIO_VERSION)),$(shell cat $(HOME)/.ssh/id_ed25519.pub $(HOME)/.ssh/id_rsa.pub 2>/dev/null | head -1))
export BR2_DL_DIR AROIO_VERSION AROIO_SSH_PUBKEY

.PHONY: test e2e web buildroot image docker-image selftest

test:
	./dev.sh test

e2e: web
	cd web && npx playwright test

web:
	cd web && npm ci --no-audit --no-fund && npx vite build

# Buildroot plus br2-external/buildroot-patches (version bumps of Buildroot packages that
# are behind upstream). Another version or other patches: fetch it again; another
# Buildroot version also starts the output from scratch (new toolchain).
BR_PATCHES = $(sort $(wildcard $(CURDIR)/br2-external/buildroot-patches/*.patch))
BR_STAMP = $(BR_VERSION) $(shell cat $(BR_PATCHES) /dev/null | cksum | cut -d' ' -f1)
buildroot:
	@if [ -d $(BR_DIR) ] && [ "$$(cat $(BR_DIR)/.aroio-stamp 2>/dev/null)" != "$(BR_STAMP)" ]; then \
		if [ "$$(cut -d' ' -f1 $(BR_DIR)/.aroio-stamp 2>/dev/null)" != "$(BR_VERSION)" ]; then \
			echo "Buildroot $(BR_VERSION): neuer Build von Grund auf"; rm -rf $(OUT); fi; \
		rm -rf $(BR_DIR); fi
	@if [ ! -d $(BR_DIR) ]; then \
		git clone -q --depth 1 --branch $(BR_VERSION) https://gitlab.com/buildroot.org/buildroot.git $(BR_DIR) && \
		for p in $(BR_PATCHES); do echo "Buildroot-Patch $$(basename $$p)"; git -C $(BR_DIR) apply $$p || exit 1; done && \
		echo "$(BR_STAMP)" > $(BR_DIR)/.aroio-stamp; fi

image: buildroot
	test -f web/dist/index.html || { echo "web/dist fehlt: zuerst 'make web'"; exit 1; }
	$(MAKE) -C $(BR_DIR) BR2_EXTERNAL=$(CURDIR)/br2-external O=$(OUT) aroio_rpi_defconfig
	$(MAKE) -C $(OUT) host-rust-bin
	HOST_DIR=$(OUT)/host BR_DIR=$(BR_DIR) tools/vendor-camilladsp.sh
	# package list with licenses for the app (aroiod.mk turns it into licenses.json)
	$(MAKE) -s -C $(OUT) show-info > $(OUT)/show-info.json
	# our own packages and the boot files (config.txt, cmdline.txt) come from this repository: fresh on every build
	$(MAKE) -C $(OUT) aroiod-dirclean aroio-web-dirclean rpi-firmware-dirclean
	$(MAKE) -C $(OUT)
	mkdir -p $(COPY_TO)
	cp $(OUT)/images/sdcard.img $(COPY_TO)/aroio-sdcard.img
	# download size: xz shrinks the empty space in the partitions to almost nothing
	xz -T0 -6 -k -f $(COPY_TO)/aroio-sdcard.img
	rm -f $(COPY_TO)/aroio-*.raucb
	cp $(OUT)/images/aroio-*.raucb $(COPY_TO)/ 2>/dev/null || true
	@echo "Fertig: $(COPY_TO)/aroio-sdcard.img"

# Buildroot output lives in a Docker volume: macOS file systems are case-insensitive,
# which breaks the kernel build, and bind mounts are slow.
RAUC_KEY_ARGS = $(if $(AROIO_RAUC_KEY),-v $(abspath $(AROIO_RAUC_KEY)):/keys/key.pem:ro -e AROIO_RAUC_KEY=/keys/key.pem \
	-e AROIO_RAUC_CERT=/work/br2-external/board/rpi/rauc/release-cert.pem)

docker-image: web
	docker build -t aroio-build docker
	docker run --rm --name $(AROIO_CONTAINER) -v $(CURDIR):/work -v $(AROIO_BUILD_VOLUME):/build -w /work $(RAUC_KEY_ARGS) \
		-e AROIO_VERSION=$(AROIO_VERSION) \
		-e AROIO_SSH_PUBKEY="$(AROIO_SSH_PUBKEY)" aroio-build \
		make image BR_DIR=/build/buildroot OUT=/build/out BR2_DL_DIR=/build/dl COPY_TO=/work/output

# image checks without hardware (after docker-image)
selftest:
	docker run --rm -v $(CURDIR):/work -v $(AROIO_BUILD_VOLUME):/build -w /work aroio-build tools/image-selftest.sh
