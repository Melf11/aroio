# br2-external: AroioOS

**Stand: Entwurf (Phase 0), noch nicht gebaut.** Symbolnamen, Versionen und Hashes werden
mit dem ersten `make` gegen Buildroot 2026.02.x geprüft und korrigiert.

- `configs/aroio_rpi_defconfig`: ein aarch64-Image für Pi 3B/3B+, 4, 5 (CM4/CM5)
- `board/rpi/`: Partitionen (genimage), config.txt/cmdline.txt, RAUC, Kernel-Fragment, systemd-Units
- `package/`: camilladsp, aroiod, aroio-web (fertig gebaute PWA aus `web/dist`)
- `patches/`: `BR2_GLOBAL_PATCH_DIR`. Buildroot selbst bleibt unverändert.

`patches/linux/0001-Add-AroioDAC-clock-driver.patch.4x-reference` ist der Treiber aus aroio-ng
(Kernel 4.x). Er muss für Kernel 6.12 portiert werden (Phase 0) und heißt dann `0001-….patch`.

Partitionen: `boot` (FAT, Kernel A/B + Firmware) · `rootfsA` · `rootfsB` (squashfs, read-only) · `data` (ext4, wächst beim ersten Start auf die Kartengröße).
