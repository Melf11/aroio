# AroioOS (Neubau)

Neues Betriebssystem und neue App für die Aroio-Streamer von ABACUS electronics.
Raspberry Pi 3B/3B+, 4 und 5, alle Aroio-Modelle (SU, EX, LT) und AroioOS auf einem normalen Pi.

- **Ton:** CamillaDSP statt BruteFIR/JACK, Abtastrate folgt der Musik, bitgenau ohne Bearbeitung
- **Raumkorrektur:** Assistent Schritt für Schritt mit Messmikrofon (UMIK-1), dazu FIR-Import für Acourate/Audiovero
- **Quellen:** Lyrion/Squeezelite, Spotify Connect, AirPlay 2, UPnP/OpenHome, Bluetooth (LDAC/aptX HD), Roon, Eingang
- **Musik:** eigene Player- und Bibliotheksansicht über Lyrion, TIDAL und Qobuz direkt in der App
- **App:** PWA (iOS und Android „Zum Home-Bildschirm“), responsiv ab 375 px, barrierefrei (WCAG 2.2 AA), Expertenmodus
- **System:** Buildroot, schreibgeschützt, A/B-Updates mit automatischem Rückfall, Übernahme alter Aroios mit Assistent

Plan, Entscheidungen und offene Fragen: [docs/NEUBAU-PLAN.md](docs/NEUBAU-PLAN.md).

## Entwickeln ohne Raspberry Pi

```bash
./dev.sh
```

- App: http://localhost:5173
- Simulator: http://localhost:5173/sim.html: die App im Rahmen eines Geräts (iPhone 13 mini, iPhone 15, Pixel, iPad,
  Laptop, Desktop, Querformat oder Mobil und Desktop nebeneinander) neben einem simulierten Aroio (Display, LEDs,
  Drehgeber, Taste, IR-Fernbedienung) und der Außenwelt: AirPlay vom iPhone, Spotify Connect, Bluetooth-Handy, UPnP, Roon,
  Messmikrofon, Störgeräusch, LAN/WLAN/Internet, Lyrion-Server, TIDAL-Anmeldung, Update, Neustart, Altgerät migrieren,
  Erststart.
- **Ton am Rechner:** Im Simulator „Ton einschalten“. Gespielt wird synthetische Musik (pro Titel anders) durch die
  echte CamillaDSP-Konfiguration aus aroiod (Presets, Raumkorrektur, Cleaner, Lautstärke). Optional ist der „virtuelle
  Raum“ hörbar, dann hört man im A/B-Vergleich die Wirkung der Raumkorrektur.
- **Raumeinmessung:** Steckt am Rechner ein UMIK-1, wird es automatisch verwendet und es wird wirklich gemessen
  (Sweeps über die Lautsprecher des Rechners, Aufnahme im Browser). Ohne UMIK läuft die Messung vollständig simuliert
  gegen den virtuellen Raum. Umschaltbar im Simulator unter „Messmikrofon“. Das echte Mikrofon geht nur über
  `http://localhost`.

Voraussetzungen: Python 3.11+, Node 20+. `./dev.sh` richtet `.venv` und `web/node_modules` beim ersten Start ein.

## Tests

```bash
./dev.sh test    # Backend (pytest), svelte-check inkl. Barrierefreiheit, Build, Übersetzungen
make e2e         # Abläufe und axe-Prüfung aller Seiten, mobil und Desktop, hell und dunkel
```

## Aufbau

| Ordner | Inhalt |
|---|---|
| `aroiod/` | Steuerdienst (Python, aiohttp): API, Wiedergabe, DSP, Raumkorrektur, Migration, Simulator-Welt |
| `web/` | App (Svelte 5, Vite) und Simulator |
| `tests/` | Backend-Tests |
| `web/e2e/` | Playwright-Tests mit axe-core |
| `br2-external/` | Buildroot-External-Tree (Entwurf) |
| `tools/` | Icons erzeugen, Übersetzungen prüfen |
| `docs/` | Plan |
