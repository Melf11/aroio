# AroioOS. Everyday development: ./dev.sh (simulator). This Makefile ties the parts together.
#
#   make test          backend tests, svelte-check, build, i18n
#   make e2e           Playwright: flows + accessibility (axe, WCAG 2.2 AA), mobile + desktop
#   make web           build the app into web/dist
#   make buildroot     fetch Buildroot (pinned, unmodified) into buildroot/
#   make image         configure + build the SD card image (needs Linux)
#   make docker-image  same, inside the build container (docker/Dockerfile)

BR_VERSION ?= 2026.02.1
OUT ?= $(CURDIR)/output

.PHONY: test e2e web buildroot image docker-image

test:
	./dev.sh test

e2e: web
	cd web && npx playwright test

web:
	cd web && npm ci --no-audit --no-fund && npx vite build

buildroot:
	test -d buildroot || git clone --depth 1 --branch $(BR_VERSION) https://gitlab.com/buildroot.org/buildroot.git buildroot

image: buildroot web
	$(MAKE) -C buildroot BR2_EXTERNAL=$(CURDIR)/br2-external O=$(OUT) aroio_rpi_defconfig
	$(MAKE) -C $(OUT)

docker-image:
	docker build -t aroio-build docker
	docker run --rm -v $(CURDIR):/work -w /work -u $$(id -u):$$(id -g) aroio-build make image
