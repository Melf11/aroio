# AroioOS (Neubau)

Neues Betriebssystem und neue App für die Aroio-Streamer von ABACUS electronics.
Raspberry Pi 3B/3B+, 4 und 5, alle Aroio-Modelle (SU, EX, LT) und AroioOS auf einem normalen Pi.

> [!IMPORTANT]
> **Privater Neubau, keine offizielle Software von ABACUS electronics.**
> Dieses Projekt ist ein privater Neubau des originalen AroioOS im Rahmen und nach den Richtlinien der
> Open-Source-Lizenzen, unter denen AroioOS und die verwendeten Komponenten veröffentlicht sind.
> Es besteht **derzeit keine Haftung und keine Gewährleistung** für Probleme, Schäden oder Datenverlust an
> Aroio-Geräten oder anderer Hardware, die durch die Nutzung entstehen. Benutzung auf eigenes Risiko.
> Für Support zu den Geräten selbst ist ABACUS electronics zuständig, nicht dieses Projekt.

- **Ton:** CamillaDSP statt BruteFIR/JACK, Abtastrate folgt der Musik, bitgenau ohne Bearbeitung
- **Raumkorrektur:** Assistent Schritt für Schritt mit Messmikrofon (UMIK-1), dazu FIR-Import für Acourate/Audiovero
- **Quellen:** Lyrion/Squeezelite, Spotify Connect (Spotify Soloist, eigener Schlüssel nötig), AirPlay 2, UPnP/OpenHome, Bluetooth (LDAC/aptX HD), Roon, Eingang, NetJack
- **Musik:** eigene Player- und Bibliotheksansicht über Lyrion, TIDAL und Qobuz direkt in der App
- **App:** PWA (iOS und Android „Zum Home-Bildschirm“), responsiv ab 375 px, barrierefrei (WCAG 2.2 AA), Expertenmodus
- **System:** Buildroot, schreibgeschützt, A/B-Updates (inklusive Kernel) von GitHub mit automatischem Rückfall, Übernahme alter Aroios mit Assistent

Plan, Entscheidungen und offene Fragen: [docs/NEUBAU-PLAN.md](docs/NEUBAU-PLAN.md).

**Demo im Browser:** https://melf11.github.io/aroio/ zeigt die App mit einem simulierten Aroio, ohne Gerät und ohne
Installation. Der Simulator (aroiod) läuft dort als Python direkt im Browser
([Pyodide](https://pyodide.org)), nichts wird an einen Server geschickt. `?neu` startet mit dem Einrichtungsassistenten.

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

- **WLAN-Einrichtung:** Ohne Kabel und WLAN öffnet der Aroio den Hotspot „Aroio-Einrichtung-XXXX“. Handys zeigen
  beim Verbinden automatisch das Einrichtungsfenster (Captive Portal). Im Simulator: „Erststart ohne Netz“, dann
  „Handy verbindet sich mit dem Hotspot“.

- **Demo für GitHub Pages:** `tools/build-demo.sh` baut die App mit dem Simulator im Browser nach `web/dist-demo`
  (`.github/workflows/pages.yml` veröffentlicht sie bei jedem Push, der `web/` oder `aroiod/` ändert). Lokal ansehen:
  `web/dist-demo` unter dem Pfad `/aroio/` ausliefern.

Voraussetzungen: Python 3.11+, Node 20+. `./dev.sh` richtet `.venv` und `web/node_modules` beim ersten Start ein.

## Am echten Aroio entwickeln (ohne SD-Karte neu zu beschreiben)

Voraussetzung: ein Entwicklungs-Image (`make docker-image`, enthält deinen SSH-Schlüssel) und SSH als `root`.

```bash
./dev.sh deploy            # aroiod + App aufs Gerät, Neustart von aroiod: wenige Sekunden
./dev.sh deploy --no-web   # nur aroiod
./dev.sh deploy --bundle   # ganzes System (Dienste, Skripte, Pakete, Kernel) per RAUC in den anderen Slot
./dev.sh deploy --off      # zurück zum Code des installierten Systems
./dev.sh logs              # Protokoll von aroiod, CamillaDSP, NetJack live
AROIO_HOST=192.168.1.80 ./dev.sh deploy
```

Der Entwicklerstand liegt auf `/data/dev` und bleibt über Neustarts aktiv, bis ein Update ein anderes System
installiert. Neu beschreiben muss man die SD-Karte nur, wenn sich die Partitionierung ändert.

## Releases und Updates

- **Bauen, testen, veröffentlichen** (wie ein manueller Job in GitLab): gebaut wird einmal, veröffentlicht werden
  genau die getesteten Dateien.
  1. *Actions › Image bauen › Run workflow* mit Version (`0.2.0` = stabil, `0.2.0-beta.1` = Pre-Release für den
     Beta-Kanal) und den Neuerungen, getrennt mit `;` (erscheinen in der App). Die Version steckt im Image, darum
     wird sie hier gewählt. Leer = Testbuild `ci-<commit>` ohne Release-Schritt.
  2. Das SD-Image aus dem Artifact `aroio-<version>` am Lauf testen (30 Tage aufgehoben).
  3. Am selben Lauf **Review deployments › release › Approve and deploy**: Der Job „release“ veröffentlicht genau
     diese Dateien als `vX.Y.Z`, ohne neu zu bauen. Ohne Freigabe verfällt er nach 30 Tagen. Freigeben dürfen die
     Personen, die in *Settings › Environments › release* eingetragen sind. Den Release-Text kann man danach auf
     GitHub noch ändern.
- **Lange Builds:** GitHubs Runner beenden einen Job nach 6 Stunden. Ein Build von Grund auf kann länger dauern:
  Dann sichert der Job seinen Zwischenstand im Cache und startet selbst den nächsten Teil, der dort weitermacht
  (höchstens 5 Teile). Danach macht der Compiler-Cache die Builds deutlich schneller.
- **GitHub Actions:** `.github/workflows/release.yml` baut das System, prüft es (`tools/image-selftest.sh`) und
  veröffentlicht nach Freigabe als Release: ein SD-Image für alle Geräte (Gerät und Soundkarte wählt man beim ersten Start), das
  signierte Update-Paket `aroio-X.Y.Z.raucb` und `SHA256SUMS`. Tests laufen bei jedem Push (`ci.yml`).
- **Aroios** fragen einmal täglich die GitHub-Releases ab. Updates lassen sich in der App installieren, mit
  „Automatisch aktualisieren“ nachts, wenn keine Musik läuft. Das neue System wird in den freien Slot
  geschrieben und beim Neustart einmal probiert. Kommt es nicht hoch, startet wieder das alte.
- **Signatur:** Die Geräte vertrauen nur Paketen, die mit dem Release-Schlüssel signiert sind
  (Zertifikat: `br2-external/board/rpi/rauc/release-cert.pem`). Der private Schlüssel liegt als
  Repository-Secret `RAUC_KEY`, nie im Repository. Entwicklungs-Images vertrauen zusätzlich ihrem eigenen
  Entwicklungsschlüssel.
- **Eigener Build-Server** (optional, schneller): selbst gehosteten Runner mit Docker einrichten und die
  Repository-Variable `AROIO_RUNNER` auf seine Labels setzen, z. B. `["self-hosted","aroio"]`. Empfohlen: mindestens
  4 Kerne, 8 GB RAM, 80 GB SSD. Ohne Variable baut GitHub selbst (erster Build mehrere Stunden).

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
| `br2-external/` | Buildroot-External-Tree: Pakete, Overlay, A/B-Start, RAUC |
| `tools/` | Icons, Übersetzungen, Image-Selbsttest, Lizenzliste |
| `.github/workflows/` | Tests (`ci.yml`), Image-Build und Release (`release.yml`) |
| `docs/` | Plan |

## Lizenz

Für den eigenen Code dieses Neubaus ist noch keine Lizenzdatei festgelegt. Die Komponenten im Image
(Linux, CamillaDSP, shairport-sync, JACK, …) behalten ihre eigenen Open-Source-Lizenzen; die Liste
steht in der App unter Einstellungen › Lizenzen. Die Werksfilter (BBC-Dip, Echo) stammen aus AroioOS 5.1 von
ABACUS electronics.
