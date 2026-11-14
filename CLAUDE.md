# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The from-scratch rebuild of AroioOS (ABACUS electronics audio streamer, Raspberry Pi 3B/4/5, all Aroio models SU/EX/LT + plain Pi). The old system lives in `../aroio-ng` and must not be modified. Plan, decisions and open questions: `docs/NEUBAU-PLAN.md`. UI text and docs are German; code and comments are English.

## Commands

```
./dev.sh                 # aroiod (simulated hardware, port 8140) + Vite (5173); simulator at /sim.html
./dev.sh test            # pytest + svelte-check (fails on a11y warnings) + vite build + i18n check
./dev.sh build           # build web/dist and serve it from aroiod on :8140 (/sim)
./dev.sh reset           # wipe the simulated device (.dev/)
.venv/bin/python -m pytest tests/test_roomcorr.py::test_level_and_time_alignment   # one backend test
cd web && npx playwright test -g "Raumkorrektur" --project=mobil                     # one e2e test
make e2e                 # Playwright flows + axe (WCAG 2.2 AA), mobile 375×812 and desktop 1280×800
node tools/i18n-check.mjs --list   # German UI texts without English translation
make image / make docker-image     # Buildroot image (br2-external is a draft, not built yet)
```

## Architecture

- **aroiod/** (Python, aiohttp) is the single control process and the only writer of `/data`. `engine.Device` holds all logic (source switching, volume, sample-rate following, DSP presets, services, migration). Everything outside the process goes through `device.world`: `sim.SimWorld` in development; the real world (CamillaDSP websocket, Lyrion JSON-RPC, BlueZ/iwd D-Bus, RAUC) is phase 1 and must implement the same methods. `python -m aroiod` without `--sim` deliberately exits until then.
- **State flow**: `hub.Hub` holds topics (`player`, `dsp`, `services`, `roomcorr`, `sim`, …); `Device.publish_*` replace a topic as a whole and push it over `/api/v1/ws`. The app never polls. REST (`web.py`, `/api/v1`) only sends commands; errors are JSON `{error, field}` with text meant for end users.
- **Config**: `config.py` declares a schema (`SCHEMA`, `F`), every change is a validated patch written atomically (`store.atomic_write_json`); unknown keys are rejected. Schema changes need a version bump and an entry in `UPGRADES`. Secrets (passwords, tokens) live separately in `secrets.json` (0600) and are never sent to the app. `/boot/userconfig.txt` of the old system is only read by `migration.py`.
- **Audio path**: exactly one source plays; a new source pauses the previous one (no mixer, so no forced rate). `dsp.camilla_config()` turns a preset into a CamillaDSP 3 config for the current source rate; FIR presets carry one file pair per rate, missing rates fall back to the nearest rate of the same family with resampling. Empty pipeline = bit-perfect. The M/S "Cleaner" matrix matches the old BruteFIR config.
- **Room correction**: `roomcorr.py` is pure maths (sweep, deconvolution, smoothing, target curves, PEQ fit with hard +3 dB total boost limit and no boost below the speaker roll-off); `wizard.RoomWizard` is the step state machine (topic `roomcorr`), A/B via a temporary `preview` preset. `SimRoom` provides a deterministic room for tests and the simulator.
- **Library**: `library.py` defines one browse model (`page`/`item`, ids `provider:kind:key`) for own music, TIDAL, Qobuz and radio. `SimLibrary` is fake data; the Lyrion JSON-RPC mapping (phase 4) must produce the same shapes.
- **Simulator audio**: `web/src/sim/audio.js` plays sound on the dev machine. It rebuilds the CamillaDSP config from the `sim` topic in Web Audio, synthesises music per track and optionally applies the simulated room (`SimRoom.MODES`). `SimWorld.mic_mode` is `sim` (virtual room, default for `./dev.sh`), `none` (tests) or `host`: then `measure()`/`level_check()` send a request via the `sim` topic and wait until the simulator page plays/records and posts to `/api/v1/sim/result/{id}`. The page auto-selects a UMIK on the host.
- **web/** (Svelte 5 runes, Vite, no router library): `lib/state.svelte.js` (WebSocket topics), `lib/router.svelte.js` (History API, focuses `main h1` after navigation), `lib/i18n.svelte.js` (German text is the key, `lib/en.js` maps it; `'Hell|Darstellung'` adds a context). Views in `src/views`, settings pages in `src/views/settings`, simulator in `src/sim` (separate entry `sim.html`, not shipped in the image).
- **br2-external/**: Buildroot external tree (aarch64, squashfs A/B + RAUC, `data` partition); Buildroot itself is fetched unmodified by `make buildroot`.

## Rules that are easy to break

- Accessibility is a gate: `svelte-check --fail-on-warnings` and the axe tests must stay clean. Use real controls (`button`, `a`, native range/radio), visible labels, `aria-live` via `announce()`/`toast()`, touch targets ≥ 44 px, no information by colour alone.
- Brand colour `#00AAAA` (`--brand`) is only for fills with `--on-brand` text; text in brand colour uses `--brand-ink`. Define colours as tokens in `src/app.css` for light and dark.
- Svelte trims leading whitespace in `{#if}` blocks: write separators as `{' · '}`.
- Every new UI text needs an English entry in `web/src/lib/en.js` (`./dev.sh test` reports missing ones).
- Backend changes that affect the app need a test in `tests/test_api.py`; flows a person goes through need a Playwright test.
