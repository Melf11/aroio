# Aroio Neubau: Plan

Stand: 14.11.2026 (Entscheidungen und Umsetzungsstand: Abschnitte 11 und 12). Grundlage: das Repo `aroio-ng` (Buildroot 2020.02, BR2_EXTERNAL `aroio/`) und `../tapedeck` (Raspberry Pi OS + Python/aiohttp + PWA + CamillaDSP + Spotify).

---

## 1. Ziele und messbare Kriterien

| Ziel | Kriterium (Abnahme) |
|---|---|
| Schneller Start | Strom an → erster Ton möglich: **≤ 8 s auf Pi 4/5, ≤ 12 s auf Pi 3**. Vorher wird der Ist-Wert des alten Systems gemessen. |
| Stabilität | 72-h-Dauertest mit FIR-Raumkorrektur bei 192 kHz ohne Aussetzer (xrun-Zähler = 0). 500 harte Stromunterbrechungen ohne defektes Dateisystem. Ein Update, das fehlschlägt, rollt automatisch zurück. |
| Audiophil | Ohne aktive Klangbearbeitung ist der Weg bitgenau (geprüft mit Testsignal und Rückmessung). Abtastrate folgt der Quelle, keine Umrechnung ohne Not. Interne Rechnung in 64-Bit-Gleitkomma. |
| Barrierefrei | WCAG 2.2 AA in allen Ansichten, AAA-Kontrast für Text in den Kernansichten. axe-core zeigt 0 Verstöße, Lighthouse Accessibility = 100. Manuell geprüft mit VoiceOver (iOS/macOS) und TalkBack. |
| Einfach | Jede Grundfunktion braucht höchstens 2 Schritte ab dem Startbildschirm. Fachbegriffe gibt es nur im Expertenmodus. Getestet mit 5 nicht-technischen Personen. |
| Wartbar | Upstream-Buildroot bleibt unverändert (Submodul, LTS). Jede Anpassung liegt im External-Tree oder als Patch-Datei. CI baut das Image und testet App und Logik bei jedem Commit. |
| Responsive | Von 375 CSS-px (iPhone 13 mini) bis Desktop, Hoch- und Querformat, Safe-Areas (Notch). |

---

## 2. Bestand: Funktionen des alten Systems (müssen alle übernommen werden)

Aus `aroio/overlay/opt/www/*.php`, `usr/bin/*`, `usr/lib/systemd/system/*` und den Schlüsseln in `userconfig.txt`:

| Bereich | Altsystem | Neu (Abschnitt 4) |
|---|---|---|
| **Quellen** | Squeezelite (LMS), Spotify (librespot / spotifyd), AirPlay 1 (shairport-sync), UPnP/DLNA (gmrender-resurrect), Bluetooth-A2DP (bluez-alsa, LDAC), Eingang der Soundkarte (`JACK_INPUT`), NetJack | Squeezelite, Spotify Connect, **AirPlay 2**, UPnP/**OpenHome** (upmpdcli), Bluetooth (BlueALSA 4, LDAC/aptX HD), Eingang, NetJack nur wenn noch genutzt (offene Frage) |
| **Mischen/Routing** | JACK + Matrix pro Quelle (`JACK_*`, `DMIX_*`, `JACKBF*`), Modi `vol-plug`, `vol-plug-ms`, `jack-bf`, `jack-bfms` | Quellen-Umschaltung ohne JACK (4.3) |
| **DSP** | BruteFIR, Filterbänke `COEFF_NAMEn` mit Dämpfung/Verzögerung, `DEF_COEFF`, M/S-Kodierung „Cleaner“ (`MSCODING`), mitgelieferte Filter, Filter-Upload per SFTP | CamillaDSP 3: FIR, PEQ, Mixer (M/S), Presets |
| **Messung** | Log-Sweep (200 s, 96 kHz) mit miniDSP UMIK-1, Aufnahme zur Auswertung bei Audiovero/Acourate | Raumkorrektur-Assistent auf dem Gerät + Acourate-Weg im Expertenmodus (Abschnitt 5) |
| **Audio-Einstellungen** | Abtastrate, Resampler-Qualität, Puffer (Squeezelite, Shairport, JACK), Startlautstärke, Soundkarte (inkl. HDMI/Klinke), Plattform (AroioSU/EX/LT/AP/OS) | Größtenteils automatisch, Rest im Expertenmodus |
| **Netzwerk** | LAN DHCP/statisch, WLAN-Suche/-Verbindung, Hotspot (hostapd/udhcpd), Hostname, Onboard-WLAN/-BT an/aus | Einrichtungs-Hotspot mit Captive Portal, sonst wie bisher |
| **Hardware** | Drehgeber (Lautstärke), Taster, Netzwerk-LED (GPIO 22), IR-Fernbedienung (lirc → LMS-Befehle), Display-Drehung + Infoscreen | Kernel-Treiber statt Daemons (4.6) |
| **System** | Update (prüfen/laden/Beta-Kanal), Logs (System, dmesg, Squeezelite, BruteFIR, JACK), Neustart, Passwort für die Weboberfläche, Sprache de/en, Credits | A/B-Update, Diagnose-Paket, alles in der App |
| **Bluetooth** | Koppeln, automatisch neu verbinden, Kopplungen löschen, Name senden | Gleiche Funktionen, Koppeln über einen Knopf mit Zeitfenster |

**Fehler im Altsystem, die beim Neubau verschwinden:** `checkuserconfig` vergleicht `"BRUTEFIR" = "ON"` (Text statt Variable), der Dienst-Symlink in `webinterface.mk` ist falsch geschrieben (`webinteraface.service`), das root-Passwort `aroio` ist fest eingebaut, SSH ist immer an, der PHP-Code baut Shell-Befehle aus Formularwerten zusammen.

---

## 3. Was von Tapedeck übernommen wird

| Übernehmen | Woher | Anpassung |
|---|---|---|
| **Spotify-Lösung** (Soloist + Web API, Updater-Timer, Ablauf-Erkennung Exit 10) und die Erkenntnis, dass librespot für viele Konten keinen Audio-Schlüssel mehr bekommt | `tapedeck/spotify.py`, `docs/SPOTIFY.md` | Für einen Lautsprecher braucht es nur Connect, die Web API fällt weitgehend weg. Klären, ob Soloist unter Buildroot (glibc) läuft. |
| **Atomares Schreiben** (Temp-Datei, fsync, rename) und **ein Schreiber pro Datei** | `tapedeck/store.py` | Unverändert |
| **Steuerung über einen Unix-Socket** zwischen Web-Dienst und Steuerprozess | `tapedeck/web.py`, `controller.py` | Bei Aroio ein Prozess `aroiod` mit getrennten Modulen |
| **CamillaDSP** zwischen Mischer und DAC, **CamillaGUI nur bei Bedarf**, beendet sich nach 30 min | `system/camilladsp/`, `docs/notizen/EXPERTENMODUS.md` | Loopback durch Quellen-Umschaltung ersetzen (4.3). Abtastrate folgt der Quelle statt fest 48 kHz. |
| **PWA-Grundgerüst** (Manifest, `apple-mobile-web-app-*`, `viewport-fit=cover`, `theme-color` hell/dunkel) | `web/index.html`, `manifest.webmanifest` | — |
| **Simulator + `dev.sh`**: App lokal ohne Pi entwickeln, Tests mit pytest | `dev.sh`, `tapedeck/dev.py`, `tests/` | Simulierte Quellen, simulierter DSP, simulierte Messung |
| **Browser-Demo auf GitHub Pages** | `demo/` | Gut für Händler und Kundschaft |
| **Hardware-Belegung im Expertenmodus** (Pins für Tasten, Drehgeber, LEDs) | `tapedeck/hwconfig.py` | Für Drehgeber, IR, LED |
| **Muster für die Migration** (vorhandene Daten nie überschreiben, `--dry-run`) | `tools/migrate_legacy.py` | Quelle ist `userconfig.txt` statt Phoniebox |
| **Start-Optimierungen**: zram statt Swap, Boot-Partition erst bei Bedarf einbinden, keine Wartezeit aufs Netz für lokale Dienste, schlanke Builds | `docs/TECHNIK.md` | Unter Buildroot fällt vieles davon schon weg |
| **Sicherheit**: Dienste ohne root, sudo nur für einzelne Aktionen, Geheimnisse mit Rechten 0600 | `system/sudoers` | polkit/sudo durch Hilfsprogramme mit `CAP_*` ersetzen |

**Nicht übernommen:** pi-gen/Raspberry Pi OS als Basis. Für ein Gerät, das schnell startet, unveränderlich ist und atomar aktualisiert wird, bleibt Buildroot besser: kleineres System, kürzerer Start, schreibgeschütztes Root-Dateisystem.

---

## 4. Zielarchitektur

### 4.0 Warum Buildroot (und wann nicht)

| | Buildroot | Raspberry Pi OS (pi-gen, wie Tapedeck) |
|---|---|---|
| Start bis Ton | ca. 5–8 s erreichbar | Tapedeck: ca. 14 s nach viel Tuning |
| Unveränderliches System + A/B-Update | Naturgemäß: ein Image, ein Artefakt | Gegen die Art von apt. Mit squashfs + RAUC möglich, dann fallen die apt-Vorteile weg |
| Reproduzierbar | Defconfig + Versionen = identisches Image | Hängt vom Stand der Debian-Paketquellen am Bautag ab |
| Größe, Dienste, Angriffsfläche | Nur was wir auswählen (≈ 100–200 MB) | Mehrere hundert MB bis über 1 GB mit Diensten, die wir abschalten müssten |
| Fremde Binaries (Soloist, Roon Bridge) | Laufen, wenn die Bibliotheken passen. Muss geprüft werden. | Laufen meist sofort |
| Lyrion auf dem Gerät | Aufwendig: Perl + viele CPAN-Module (im Altsystem ~80 eigene Pakete) | Fertiges Debian-Paket |
| Python mit numpy/scipy | Buildroot-Pakete vorhanden | apt/pip |
| Bauzeit | 1–2 h voll, mit Cache in CI wenige Minuten | ähnlich |

**Entscheidungsregel für Phase 0:** Buildroot bleibt, wenn (1) Soloist und Roon Bridge laufen und (2) Lyrion auf dem Gerät ohne ~80 selbst gepflegte Perl-Pakete auskommt. Für (2) wird geprüft, ob das offizielle Lyrion-Archiv für ARM-Linux mit seinen mitgelieferten CPAN-Modulen auf dem Buildroot-Perl läuft. Scheitert eines davon dauerhaft, ist die Alternative ein **schreibgeschütztes Debian-Image** (pi-gen + squashfs + RAUC): leichtere Pakete, dafür langsamerer Start und größeres Image.

### 4.1 Betriebssystem und Build

- **Buildroot 2026.02 LTS** als **unverändertes Git-Submodul**. Patches für Pakete liegen über `BR2_GLOBAL_PATCH_DIR` im External-Tree, eigene Pakete unter `package/`. Updates im LTS-Zweig sind dann ein Submodul-Bump.
- **aarch64, ein Image für Pi 3B/3B+, 4, 5 (und CM4/CM5)**. Kernel aus dem Raspberry-Pi-Kernel 6.12+ mit allen DTBs, die Firmware wählt beim Start. **Pi 2 fällt weg (entschieden 14.11.2026).** Für Pi-2-Geräte im Feld gibt es keine Migration; das alte System bleibt dort.
- **Kernel**: eigener schlanker Defconfig. Treiber, die beim Start gebraucht werden (I²S, Aroio-DAC-Clock-Patch, SD, USB-Audio), fest einbauen, keine initramfs. `PREEMPT` (Low-Latency). `PREEMPT_RT` ist seit 6.12 im Hauptkernel, wird im Dauertest gemessen und nur genommen, wenn es messbar hilft. CPU-Governor `performance`, IRQ-Affinität für I²S/USB.
- **Partitionen** (SD/eMMC):
  ```
  p1  boot (FAT)        Firmware, config.txt, Kernel A/B, autoboot/tryboot
  p2  rootfs A (squashfs, read-only)
  p3  rootfs B (squashfs, read-only)
  p4  data (ext4, journal; Einstellungen, Filter, Messungen, Spotify-Daten, Logs als Ringpuffer)
  ```
  Der alte Ansatz (180-MB-initramfs von FAT ins RAM laden) wird durch squashfs ersetzt. Das spart Startzeit und RAM.
- **Updates: RAUC** mit signierten Bundles und A/B. Boot-Zähler über die Pi-Firmware (`tryboot`) oder U-Boot. Startet das neue System nicht bis „gesund“ (aroiod meldet bereit), kommt beim nächsten Start automatisch wieder A. Kanäle: stabil / beta. Offline-Update per USB-Stick oder Datei-Upload in der App.
- **Init**: systemd minimal (ohne `resolved`, `homed` und Ähnliches). Netzwerk mit `systemd-networkd` + **iwd** (schneller und schlanker als wpa_supplicant + ifplugd + udhcpc). mDNS mit avahi (`aroio.local`).
- **Dienste, die beim Start gebraucht werden**: Kernel → `camilladsp` → `aroiod` → Quellen. Alles, was Netz braucht, startet parallel und blockiert den Ton nicht. Gemessen wird mit `systemd-analyze critical-chain`, in CI als Grenzwert.
- **Sicherheit**: kein festes root-Passwort, SSH aus (im Expertenmodus einschaltbar, nur mit Schlüssel). Alle Dienste als eigene Benutzer.

### 4.2 Komponenten

```
 Handy/Desktop (PWA) ──HTTPS/WS──▶ aroiod (Python, aiohttp) ──┬─ Konfiguration /data/config.json (atomar)
                                     │                          ├─ CamillaDSP Websocket (Lautstärke, Presets, Pegel, Rate)
                                     │                          ├─ Quellen-Manager (wer spielt, wer pausiert)
                                     │                          ├─ Raumkorrektur (numpy/scipy)
                                     │                          ├─ Netzwerk (iwd/networkd D-Bus), Bluetooth (BlueZ D-Bus)
                                     │                          ├─ Update (RAUC D-Bus), Diagnose
                                     │                          └─ Musikserver-Proxy (LMS JSON-RPC)
 Quellen:  squeezelite · Spotify Connect · shairport-sync (AirPlay 2 + nqptp) · upmpdcli+mpd · BlueALSA · Eingang
              └──────────────▶ ALSA Loopback ──▶ CamillaDSP 3 ──▶ DAC (Aroio-HAT / USB / HDMI)
 Drehgeber/Taster/IR (evdev) ──▶ aroiod
```

- **aroiod** in Python 3 + aiohttp, nach dem Muster von Tapedeck, damit Code und Wissen weiterverwendet werden. Die Steuerung ist nicht zeitkritisch, der Ton läuft komplett in nativen Programmen (CamillaDSP in Rust, squeezelite und shairport in C). aroiod ist ein Prozess mit Modulen und hat eine versionierte JSON-API (`/api/v1`) plus WebSocket für Live-Zustand (Titel, Pegel, Lautstärke).
- **Keine Shell-Skripte mehr als Logik**: Die rund 40 Skripte in `usr/bin` werden zu getesteten Python-Modulen. Shell bleibt nur für einfache systemd-Hilfen.
- **Konfiguration**: eine Datei `/data/config.json` mit Schema (pydantic oder jsonschema) und Versionsnummer. Migrationen zwischen Schema-Versionen laufen als Code mit Tests. Die Konfigurationen der Quellen (`shairport-sync.conf`, CamillaDSP-YAML …) erzeugt aroiod aus Vorlagen nach `/run`, statt mit `sed` in `/etc` zu schreiben.

### 4.3 Tonweg: audiophil und einfach

- **CamillaDSP 3** ersetzt **BruteFIR + JACK**. Was es abdeckt:
  - FIR-Faltung mit Dateien in `FLOAT64LE`. Die vorhandenen **Acourate-`.dbl`-Filter lassen sich direkt laden**.
  - PEQ/Biquads, Loudness, Delay, Gain, **Mixer für M/S („Cleaner“)**, Filterbänke als Presets.
  - Lautstärke mit Rampe, Pegelanzeige, Steuerung per WebSocket.
  - Rechnet in 64-Bit-Gleitkomma, ist stabil und wird aktiv gepflegt.
- **Abtastrate folgt der Quelle** (Standard): Die Quelle schreibt in ihrer Rate in den Loopback. CamillaDSP meldet einen Ratenwechsel, aroiod lädt dann die passende Konfiguration mit den FIR-Filtern für diese Rate (44,1/48/88,2/96/176,4/192 kHz). Das Altsystem nutzte eine feste Rate (`RATE`) und Resampling. Im Expertenmodus ist eine feste Rate mit hochwertigem Resampler (CamillaDSP AsyncSinc) wählbar.
- **Bitgenau**: Ohne Filter und bei 0 dB ist der Weg S32 → f64 → S32 verlustfrei. Das wird in CI mit einer Testdatei geprüft (Prüfsumme der Rückaufnahme über Loopback).
- **Lautstärke**: Hat der DAC einen Hardware-Mixer, wird der genutzt, sonst die Lautstärke in CamillaDSP (64 Bit, mit Dither am Ausgang). Eine Lautstärke gilt für alle Quellen. Spotify, AirPlay und Bluetooth laufen intern auf 100 % und werden auf die Systemlautstärke abgebildet, sodass der Regler im Handy die Aroio-Lautstärke stellt.
- **Quellen-Umschaltung statt Mischen**: Es spielt immer genau eine Quelle (wie bei modernen Streamern). Startet eine neue, pausiert aroiod die alte über deren Schnittstelle (LMS JSON-RPC, AirPlay über D-Bus/MPRIS, Spotify über Connect/Websocket, Bluetooth über AVRCP, MPD). Damit entfallen dmix (das eine feste Rate erzwingt) und JACK. Die alte Routing-Matrix (`JACK_*`, `DMIX_*`) braucht es nicht mehr.
- **Puffer**: Feste, auf jeder Plattform gemessene Werte statt Nutzer-Einstellungen. Im Expertenmodus bleiben `chunksize`, `target_level` sowie die Puffer von squeezelite und shairport einstellbar.
- **Echtzeit**: CamillaDSP mit `SCHED_FIFO`, Speicher gesperrt (`mlockall`), auf Pi 4/5 optional ein eigener CPU-Kern (`isolcpus` + Affinität).

### 4.4 Quellen

| Quelle | Lösung | Bemerkung |
|---|---|---|
| Lyrion/LMS | squeezelite (aktuell, mit DSD/DoP, ALAC über ffmpeg/alac) | Wie bisher, Name = Gerätename |
| Spotify | **Spotify Connect** mit Soloist (wie in Tapedeck), Ausweichlösung go-librespot | Kein Partnerprogramm (entschieden). Kundschaft braucht deshalb einen eigenen Soloist-Key: Der Einrichtungs-Assistent führt mit Bildern Schritt für Schritt durch developer.spotify.com. Ob go-librespot mit dem jeweiligen Konto funktioniert, prüft die Box automatisch; dann ist kein Key nötig. |
| AirPlay | **shairport-sync mit AirPlay 2** (+ nqptp) | Neu: Multiroom mit Apple-Geräten |
| UPnP/DLNA | **upmpdcli + MPD** (UPnP-Renderer + OpenHome) | Besser als gmrender, funktioniert mit BubbleUPnP, Linn Kazoo, mConnect |
| Bluetooth | BlueALSA 4 mit LDAC/aptX HD/AAC, Koppeln mit Zeitfenster | Lautstärke über AVRCP auf die Systemlautstärke |
| Eingang | Capture der Soundkarte direkt in CamillaDSP (eigene Konfiguration) | Für AroioSU/EX mit Eingang |
| Roon | **Roon Bridge** als optionales Paket, Roon Ready später | Wichtige Zielgruppe bei audiophiler Kundschaft |
| NetJack | nur wenn noch im Einsatz (offene Frage 6) | sonst streichen |

### 4.5 Musikbibliothek und Lyrion/LMS: Empfehlung

**Befund:** Im alten Image läuft LMS nicht auf dem Aroio. Der Defconfig enthält kein Perl-Paket, `slimserver` ist nicht aktiviert. Aroio ist ein **Player**, der Server läuft bei der Kundschaft (NAS/PC). LMS heißt seit 2024 **Lyrion Music Server**, wird von der Community aktiv weiterentwickelt (v9) und hat mit dem Skin **„Material“** bereits eine moderne, responsive Oberfläche. Alt sieht nur der Standard-Skin aus.

**Entschieden (14.11.2026): Lyrion bleibt, die Oberfläche wird neu gebaut.**

**Neue Player-Ansicht:** Cover groß, Titel/Album/Künstler, Format und Auflösung (z. B. „FLAC · 24 Bit · 96 kHz“, „bitgenau“ oder „mit Raumkorrektur“), Fortschritt mit Sprungmarke, Play/Pause/Weiter/Zurück, Zufall/Wiederholen, Lautstärke, Warteschlange (sortieren, entfernen, „als Nächstes“), Quelle. Liedtexte und Künstlerinfos, wo Lyrion sie liefert. Querformat und Desktop zweispaltig (Player + Warteschlange/Bibliothek).

**Neue Bibliotheksansicht:** Startseite mit „Zuletzt gehört“, „Neu hinzugefügt“, Favoriten. Dazu Künstler, Alben (Raster mit Cover), Genres, Komponisten, Ordner, Playlisten, Radio und eine Suche über alles (lokal + TIDAL + Qobuz). Albumseite mit Titelliste, Auflösung, „Alles abspielen“/„Zufällig“/„Zur Warteschlange“. Lange Listen werden virtualisiert und seitenweise geladen, damit auch 100 000 Titel flüssig laufen. Alles mit Tastatur und Screenreader bedienbar.

1. **Eigene Musik-Ansicht in der Aroio-PWA** über die Lyrion-JSON-RPC/Comet-Schnittstelle: Läuft gerade, Warteschlange, Bibliothek (Künstler/Alben/Genres/Ordner), Suche, Favoriten, Radio, Playlisten, alles im Aroio-Design und barrierefrei. Die Bibliothek bleibt auf dem vorhandenen Server, **eine Migration ist dafür nicht nötig**, und Plugins (Qobuz, TIDAL, Radio, Multiroom-Sync) bleiben erhalten.
2. **Optional Lyrion auf dem Aroio** (Pi 4/5 mit USB-Platte oder NAS-Freigabe) als eigenes Paket, das nicht beim Start läuft. Für Kundschaft ohne eigenen Server.
3. Für Fortgeschrittene ein Link auf Material Skin.

**Wenn ihr den Server doch ersetzen wollt** (z. B. MPD-basiert mit eigener Bibliotheks-API), ist ein Migrations-Assistent Pflicht. Er liest über die JSON-RPC des laufenden Lyrion: Musikordner, Playlisten (`.m3u`), Favoriten (`favorites.opml`), Radiosender, Bewertungen und Wiedergabezähler (Plugin-Daten), Player-Zuordnungen. Dazu kommt ein Abgleich, welche Titel gefunden wurden. Das ist ein großes eigenes Teilprojekt (Scanner, Tags, Cover, Streaming-Dienste) und verliert das Plugin-Ökosystem. **Ich rate davon ab** und würde es höchstens als spätere Phase nach Erfolg von Punkt 1 betrachten.

### 4.5a TIDAL und Qobuz

Ziel: TIDAL und Qobuz erscheinen in der App gleichrangig neben der eigenen Bibliothek (Durchsuchen, Suche, Favoriten, Playlisten, Abspielen in voller Auflösung). Es gibt drei Wege, die rechtlich und technisch verschieden sind:

| Weg | Wie | Bewertung |
|---|---|---|
| **A: Über Lyrion-Plugins** (Empfehlung für den Start) | Die etablierten Plugins „TIDAL“ und „Qobuz“ für Lyrion. Unsere Bibliotheksansicht zeigt ihre Menüs über JSON-RPC als eigene Bereiche „TIDAL“ und „Qobuz“. Die Anmeldung läuft in der Aroio-App (Ablauf in Phase 0 prüfen: Gerätecode bei TIDAL, Zugangsdaten bei Qobuz). | Schnell umsetzbar, im LMS-Umfeld seit Jahren erprobt. Voraussetzung: Lyrion läuft, entweder bei der Kundschaft oder auf dem Aroio. |
| **B: TIDAL Connect / Qobuz Connect** | Die App des Dienstes auf dem Handy wählt den Aroio als Lautsprecher (wie Spotify Connect). | Für Kundschaft am bequemsten. Braucht wie bei Spotify eine **Hersteller-Zertifizierung** mit geschlossenem SDK. Für Qobuz Connect lohnt eine Anfrage (hifi-orientiert). |
| **C: Eigener Client in aroiod** | Direkter Zugriff auf die Dienst-APIs | Abgeraten: Wiedergabe in voller Länge ist ohne Partnervertrag nur mit inoffiziell beschafften Schlüsseln möglich (Verstoß gegen die Nutzungsbedingungen, kann jederzeit abgeschaltet werden). |

**Folge für Lyrion auf dem Aroio:** Damit TIDAL/Qobuz auch ohne eigenen Server funktionieren, wird „Lyrion auf dem Aroio“ von optional zu **eingebaut, startet bei Bedarf**: Aktiviert jemand TIDAL oder Qobuz und hat keinen eigenen Lyrion-Server, startet der Aroio seinen eigenen (nicht im Startpfad des Tons, auch auf dem Pi 3 lauffähig). Hat die Kundschaft einen Server, nutzt der Aroio dessen Plugins.

Zusätzlich bringt **Roon Bridge** TIDAL und Qobuz für Roon-Kundschaft mit.

### 4.6 Hardware

- **Drehgeber** über das Kernel-Overlay `rotary-encoder`, **Taster** über `gpio-keys`, **IR** über `gpio-ir` + rc-core/`ir-keytable` (statt lirc-Daemon), **LEDs** über `gpio-led`. aroiod liest alles per evdev. Belegung und Fernbedienung anlernen im Expertenmodus (Muster aus Tapedeck `hwconfig.py`).
- **Plattformerkennung** (AroioSU/EX/LT/AP) über HAT-EEPROM bzw. die I²C-Kennung des DACs statt `PLATFORM` in einer Textdatei. Einen Fallback in der Konfiguration gibt es weiterhin.
- **Display/Infoscreen**: kleine Statusanzeige (Name, IP, Quelle, Titel) direkt auf das Framebuffer-Gerät (DRM), ohne X/Wayland. Zeigt beim Einrichten einen **QR-Code zur App**.

### 4.7 Netzwerk und Einrichtung

- **Erststart ohne Netz**: Hotspot „Aroio-Einrichtung“ mit Captive Portal, das direkt den Einrichtungs-Assistenten der PWA öffnet (Sprache → Name → WLAN wählen oder LAN → Spotify/AirPlay/… an → Raumkorrektur jetzt oder später).
- **Finden der Box**: `aroio.local` per mDNS, zusätzlich QR-Code auf Display/Karton und als Fallback eine Seite „Gerät finden“ (Abacus-Server, nur wenn erlaubt). Manche Android-Geräte lösen `.local` nicht auf (Tapedeck-Erfahrung).

---

## 5. Raumkorrektur mit Schritt-für-Schritt-Assistent (Stepper)

**Grundsatz:** Wer kein Techniker ist, kommt mit einem Messmikrofon und 10 Minuten zu einer guten Korrektur. Wer Experte ist, behält den Weg über Acourate/Audiovero.

### 5.1 Ablauf in der App

Jeder Schritt ist ein eigener Bildschirm mit genau einer Aufgabe, Fortschrittsanzeige („Schritt 3 von 7“), Ansage per `aria-live` und „Abbrechen“ jederzeit:

1. **Mikrofon anschließen**: Das UMIK-1 (USB 2752:0007) wird erkannt. Die Kalibrierdatei wird per Seriennummer automatisch geladen (miniDSP) oder hochgeladen. Andere USB-Messmikrofone gehen im Expertenmodus.
2. **Aufstellen**: Bild „Mikrofon auf Ohrhöhe am Hörplatz, nach oben zeigen“.
3. **Pegel prüfen**: Rosa Rauschen steigt langsam an, bis der Pegel passt. Die Lautstärke wird automatisch begrenzt (Schutz für Lautsprecher und Ohren).
4. **Messen**: Pro Kanal ein Log-Sweep (Farina, ca. 8 s) an **3–5 Positionen** rund um den Hörplatz („Mikrofon jetzt 30 cm nach links“). Läuft etwas schief (Störgeräusch, Übersteuerung, kein Signal), wiederholt der Assistent den Schritt mit einem verständlichen Hinweis.
5. **Klangcharakter wählen**: „Neutral“, „Warm“ oder „Hell“, mit Kurve als Bild. Im Expertenmodus eine eigene Zielkurve.
6. **Berechnen** auf dem Gerät (siehe 5.2), mit Fortschrittsanzeige.
7. **Vorher/Nachher**: Kontrollmessung, Kurven übereinander, A/B-Schalter zum Hören. Speichern als Preset („Wohnzimmer“).

### 5.2 Berechnung (aroiod, numpy/scipy)

- Entfaltung → Impulsantwort pro Position und Kanal, Mikrofon-Kalibrierung, frequenzabhängiges Fenster, psychoakustische Glättung, Mittelung der Positionen.
- Pegel- und Laufzeitabgleich L/R aus der Impulsantwort.
- **Standard (für alle): automatische PEQ** (bis 10 Biquads je Kanal, vor allem Absenkungen, höchstens +3 dB Anhebung, Korrektur hauptsächlich unterhalb ~500 Hz, wo der Raum dominiert). Robust, geringe Latenz, läuft auf jedem Pi.
- **Expertenmodus: FIR** (gemischtphasig, je Abtastrate erzeugt). CamillaDSP faltet partitioniert. Die Rechenlast pro Plattform wird gemessen, Grenze z. B. 65 536 Taps bei 192 kHz auf Pi 4.
- Ergebnis ist ein CamillaDSP-Preset. Die Messrohdaten werden gespeichert, damit sich später neu berechnen lässt.
- **Tests**: synthetische Räume (bekannte Moden/Reflexionen) in CI, damit sich Änderungen am Algorithmus messen lassen.

### 5.3 Acourate/Audiovero-Weg (Expertenmodus)

- Messaufnahme als WAV herunterladen (wie bisher für Audiovero).
- FIR-Filter (`.dbl`/`.wav`, je Rate) hochladen statt per SFTP, mit Prüfung (Länge, Rate, Pegel), als Filterbank/Preset benennen. Dämpfung und Verzögerung pro Bank wie bisher (`COEFF_ATTn`, `COEFF_DELAYn`).
- Umschalten zwischen Presets in der App, per Fernbedienung oder Taster.

> Das Mikrofon im Handy ist keine Alternative für die Korrektur: unkalibriert und mit eigener Signalverarbeitung. Außerdem ginge `getUserMedia` nur über HTTPS. Höchstens für eine grobe Pegelprüfung denkbar.

---

## 6. Web-App (PWA)

### 6.1 Technik

- **Svelte 5 + Vite**, Ausgabe als statische Dateien. Gründe: kleine Bundles (schnell auf dem Pi und im Handy), **eingebaute Barrierefreiheits-Prüfungen des Svelte-Compilers**, wartbarer als handgeschriebenes DOM bei dieser Größe. Gebaut wird in CI (Node), Buildroot bekommt nur das fertige Archiv. Node gehört damit nicht in den Image-Build.
- Kommunikation: REST `/api/v1` + ein WebSocket für Live-Zustand. Ohne offene App läuft kein Polling.
- Sprachen: Deutsch und Englisch (wie bisher), alle Texte in Sprachdateien.
- Entwicklung mit Simulator (`dev.sh` nach Tapedeck-Muster), Playwright-Tests auf 375×812 (iPhone 13 mini), 390, 768, 1280, 1920 px.

### 6.2 „Zum Home-Bildschirm“ auf iOS und Android

- iOS: `manifest.webmanifest`, `apple-touch-icon` (180 px), `apple-mobile-web-app-capable`, `apple-mobile-web-app-status-bar-style`, `viewport-fit=cover` und `env(safe-area-inset-*)`. Das funktioniert auch über HTTP und startet als Vollbild-App (in Tapedeck erprobt).
- **Android/Chrome installiert nur aus einem sicheren Kontext (HTTPS) als echte App.** Über `http://aroio.local` entsteht nur eine Verknüpfung, die im Browser öffnet. Auch der Service Worker (Offline-Hülle, schnelle Starts) braucht HTTPS.
- **Empfehlung: lokales HTTPS mit echtem Zertifikat.** Jedes Gerät bekommt eine eigene Adresse wie `<geräte-id>.aroio.net`, die auf seine lokale IP zeigt. Abacus stellt dafür ein Wildcard- bzw. Pro-Gerät-Zertifikat über einen kleinen Dienst aus (DNS-01 mit Let's Encrypt, Prinzip wie `plex.direct`). `aroio.local` leitet dorthin weiter. Ohne Internet bleibt `http://aroio.local` als Rückfall. → Offene Frage 4, weil dafür Abacus-Infrastruktur nötig ist.

### 6.3 Design

- **Primärfarbe bleibt `#00AAAA` („ABACUS Petrol“ aus `css/style.css`).**
- **Wichtig für die Barrierefreiheit:** `#00AAAA` hat auf Weiß nur **2,9 : 1** Kontrast und Weiß darauf ebenfalls 2,9 : 1. Für Text und Symbole reicht das nicht (AA verlangt 4,5 : 1). Lösung im neuen Farbschema:
  - `#00AAAA` für Flächen, Akzente, Fortschritt, aktive Zustände, **mit dunkler Schrift darauf** (z. B. `#062626` ≈ 7 : 1).
  - Für Text und Links auf hellem Grund eine dunklere Stufe desselben Farbtons, z. B. `#007A7A` (≈ 5,2 : 1 auf Weiß).
  - Im Dunkelmodus ist `#00AAAA` auf Fast-Schwarz direkt als Text nutzbar (≈ 6,5 : 1).
  - Neutrale Töne leicht in Richtung Petrol abgestimmt, dazu eine Warnfarbe und eine Fehlerfarbe, beide nicht nur über Farbe unterscheidbar (Symbol + Text).
- Hell- und Dunkelmodus automatisch (`prefers-color-scheme`), Schalter in den Einstellungen.
- Schrift in `rem`, Zoom nicht sperren (anders als Tapedeck: kein `user-scalable=no`), Text bis 200 % ohne Abschneiden.
- Bewegungen nur, wenn `prefers-reduced-motion` es erlaubt.

### 6.4 Barrierefreiheit (verbindlich)

- Semantisches HTML, Landmarks, eine `h1` pro Ansicht, sichtbarer Fokus, vollständige Tastaturbedienung am Desktop.
- Touch-Ziele ≥ 44×44 px, Lautstärkeregler als echter `role="slider"` mit `aria-valuetext` („Lautstärke 35 Prozent“), dazu Plus/Minus-Tasten.
- Live-Bereiche für Titelwechsel, Fortschritt im Assistenten und Fehler, ohne Dauergeplapper.
- Keine Information nur über Farbe, keine Zeitlimits, Bestätigung bei folgenreichen Aktionen (Zurücksetzen, Update).
- Einfache Sprache: kurze Sätze, keine Abkürzungen im einfachen Modus, Hilfetexte direkt am Element.
- Prüfung: axe-core in Playwright (CI-Gate), Lighthouse, manuelle Durchgänge mit VoiceOver/TalkBack vor jedem Release.

### 6.5 Aufbau der App

**Einfacher Modus (Standard):**
- **Start**: Was läuft (Cover, Titel, Quelle), großer Lautstärkeregler, Play/Pause/Weiter, Quelle wechseln.
- **Musik**: Bibliothek über Lyrion (4.5), Favoriten, Radio.
- **Klang**: Raumkorrektur (Assistent starten, Preset wählen, an/aus), Klangcharakter, Cleaner (M/S) an/aus mit Erklärung.
- **Einstellungen**: Name, WLAN/LAN, Dienste an/aus (Spotify, AirPlay, Bluetooth, UPnP, Roon), Bluetooth koppeln, Updates (automatisch), Sprache, Hilfe, **Expertenmodus an/aus**.

**Expertenmodus** (blendet zusätzliche Bereiche ein, nichts wird umgebaut):
- Ton: Ratenverhalten (folgen/fest), Resampler, Puffer, Ausgabegerät, Startlautstärke, Lautstärkegrenze.
- DSP: Presets/Filterbänke, FIR-Import, PEQ manuell, eigene Zielkurve, CamillaGUI (bei Bedarf gestartet), YAML ansehen/bearbeiten.
- Netzwerk: statische IP, DNS, Hotspot.
- Hardware: Drehgeber/Taster/IR anlernen, Display-Drehung.
- System: Logs (System, Kernel, je Quelle, CamillaDSP), Diagnose-Paket herunterladen, SSH, Update-Kanal beta, Update aus Datei, Werkseinstellungen.

---

## 7. Migration bestehender Aroios (mit Assistent)

**Befund:** Das alte System läuft komplett im RAM (initramfs) und speichert alles auf der FAT-Partition `/boot`: `userconfig.txt`, `filter/`, `version`, `Logsweep/`. Dadurch kann ein Übergangs-Image die SD-Karte sicher umbauen, während das alte System läuft.

### 7.1 Ablauf

1. **Altes Update-System nutzen**: Über den bestehenden Updater (`update`, Update-Server `aroio-4`) wird ein **Übergangs-Image** im alten Format ausgeliefert. Für Kundschaft sieht das aus wie ein normales Update.
2. Das Übergangs-Image startet (wie bisher aus dem RAM) und:
   1. sichert `userconfig.txt`, `filter/` und ggf. Messungen in den RAM und zusätzlich auf die FAT-Partition (`/boot/migration-backup.tar`);
   2. legt **im freien Bereich der Karte** die neuen Partitionen an (rootfs A/B, data). Die alte FAT-Partition wird dabei nicht angefasst, bis alles geschrieben und geprüft ist;
   3. schreibt das neue System, prüft Prüfsummen und legt das Backup nach `/data/migration/`;
   4. stellt **erst ganz am Ende** `config.txt`/`autoboot` auf das neue System um. Das ist ein einzelner kleiner Schreibvorgang. Fällt vorher der Strom aus, startet einfach wieder das alte System.
   → Klären: Auf echten Geräten prüfen, ob hinter der FAT-Partition genug Platz frei ist (genimage legt nur `boot.vfat` an, Karten ≥ 4 GB). Sonst wird die FAT-Partition vorher verkleinert (mit Backup).
3. **Erster Start des neuen Systems → Migrations-Assistent in der App** (Stepper):
   1. „Willkommen beim neuen Aroio. Wir haben deine Einstellungen übernommen.“
   2. Liste: Name, Netzwerk, aktive Quellen, Lyrion-Server, Lautstärke, Filterbänke → Presets, Cleaner. Jeweils mit ✓ oder „bitte prüfen“.
   3. Nur wo nötig eine Frage, z. B. „Du hast Filter für 96 kHz. Sollen sie auch für andere Abtastraten erzeugt werden?“ oder „Spotify muss neu verbunden werden.“
   4. Testton links/rechts, Lautstärke prüfen.
   5. Optional: Raumkorrektur neu messen.
4. **Rückweg**: Bis zum Abschluss des Assistenten lässt sich das alte System aus dem Backup wiederherstellen (Expertenmodus, oder per Taste beim Start).

### 7.2 Zuordnung alter Schlüssel

| Alt (`userconfig.txt`) | Neu |
|---|---|
| `HOSTNAME`, `PLAYERNAME` | `device.name` (ein Name für alle Dienste, Expertenmodus: getrennt) |
| `LAN_*`, `WLAN_*`, `WLANSSID`, `WLANPWD`, `DHCP`, `IPADDR` … (inkl. 3.x-Altnamen, wie in `checkuserconfig`) | `network.*` → iwd/networkd |
| `AUDIO_OUTPUT` (`vol-plug`/`-ms`/`jack-bf`/`jack-bfms`), `MSCODING`, `BRUTEFIR` | `dsp.enabled`, `dsp.ms_cleaner` |
| `RAW_PLAYER`, `RAW_PLAYERMS`, `JACK_*`, `DMIX_*`, `JACKBF*` | `sources.<name>.enabled` (alle bisher genutzten Quellen werden aktiviert) |
| `COEFF_NAMEn`, `COEFF_ATTn`, `COEFF_DELAYn`, `DEF_COEFF`, `SCOEFF_*` | `dsp.presets[]` mit FIR-Pfaden aus `filter/`, aktives Preset |
| `RATE`, `RESAMPLING` | `audio.rate_mode` (feste Rate → „fest“, sonst „folgen“), Resampler-Qualität |
| `SQUEEZE_*`, `SP_*`, `JACKBUFFER`, `JACKPERIOD`, `BF_PARTITIONS` | Expertenwerte. Übernommen werden nur Werte, die vom alten Standard abwichen. |
| `SERVERNAME`, `SERVERPORT`, `SQUEEZEUSER`, `SQUEEZEPWD` | `sources.squeezelite.server`, Zugangsdaten verschlüsselt in `/data/secrets` |
| `VOLUME_START` | `audio.start_volume` |
| `DISPLAY_ROTATE` | `display.rotate` |
| `ONBOARD_WIFI`, `ONBOARD_BLUETOOTH`, `BTRECONNECT` | `hardware.*`, `bluetooth.*` |
| `USERPASSWD` | Zugangsschutz der App (optional, neu gehasht) |
| `USEBETA`, `UPDATESERVER` | `update.channel` |
| `PLATFORM`, `SOUNDCARD` | Abgleich mit der Erkennung. Gibt es Unterschiede, fragt der Assistent nach. |
| `MEASUREMENT_OUTPUT`, `LOAD_PREFILTER`, `KNOWN_VERSION` | entfallen |

Die Zuordnung ist ein eigenes Python-Modul `migration/` mit Tests aus **echten `userconfig.txt` von Kundengeräten/Händlern** (anonymisiert). Alternativ läuft dieselbe Migration aus einem hochgeladenen Backup (`userconfig.txt` + Filter-ZIP), wenn jemand die neue Karte frisch flasht.

---

## 8. Repository-Struktur (Vorschlag, neues Repo `aroio`)

```
buildroot/                 Git-Submodul, 2026.02.x LTS, unverändert
br2-external/
  configs/aroio_defconfig  (aarch64, Pi 3/4/5) + Fragmente (debug, dev)
  board/rpi/               genimage, post-build, post-image, config.txt-Vorlage, rauc, kernel config + patches
  package/                 camilladsp, aroiod, aroio-web, soloist, nqptp, upmpdcli, roon-bridge, lyrion (optional) …
  patches/                 BR2_GLOBAL_PATCH_DIR
  rootfs-overlay/          nur statische Dateien (systemd-Units, udev-Regeln)
aroiod/                    Python-Paket + Tests + Simulator (dev.sh)
web/                       Svelte-PWA + Playwright/axe-Tests
roomcorr/                  Mess-/Berechnungsbibliothek + synthetische Testräume
migration/                 userconfig → config.json, Übergangs-Image
docs/                      Technik, Bedienung, Fehlersuche, Entwicklung (Tapedeck-Muster)
.github/workflows/         Tests, Web-Build, Image-Build (Cache), Boot-Zeit-Grenzwert, Demo auf Pages
```

`CLAUDE.md` im neuen Repo mit Build-, Test- und Simulator-Befehlen.

---

## 9. Phasen

| Phase | Inhalt | Ergebnis / Abnahme |
|---|---|---|
| **0 Machbarkeit** | 1) Startzeit des Altsystems messen; Buildroot 2026.02 aarch64 Minimal-Image auf Pi 3/4/5 mit Aroio-DAC-Patch → Startzeit. 2) Soloist auf Buildroot (glibc, PipeWire-Abhängigkeit) lauffähig? 3) CamillaDSP-Ratenwechsel mit Loopback + Aroio-HAT, xrun-frei. 4) Freier Platz/Partitionen auf echten Alt-Geräten, Probe-Umbau. 5) Lokales HTTPS (Konzept + Prototyp). | Entscheidungsvorlage mit Messwerten; offene Fragen beantwortet |
| **1 Basissystem** | Buildroot-Tree, Kernel, Partitionen, RAUC + Rollback, Netzwerk (iwd/networkd), Hotspot, CamillaDSP, alle Quellen, Quellen-Umschaltung, Hardware (Drehgeber/IR/LED) | Image spielt alle Quellen, Update mit Rollback, Startzeit-Ziel erreicht, 72-h-Test grün |
| **2 aroiod + PWA-Kern** | API, Konfiguration, Simulator, Design-System (Farben/Komponenten), Start/Einstellungen/Einrichtungs-Assistent, Expertenmodus, iOS/Android-Installation | Alle Funktionen des Altsystems in der App bedienbar; axe 0 Verstöße |
| **3 Klang** | DSP-Presets, Cleaner, FIR-Import/Filterbänke, **Raumkorrektur-Assistent** (PEQ, dann FIR), A/B | Messung → Preset in < 15 min durch Testperson ohne Vorwissen |
| **4 Musik & Spotify** | Lyrion-Ansicht in der PWA, Spotify Connect, AirPlay 2, UPnP/OpenHome, Roon Bridge | Bibliothek durchsuchen und abspielen ohne Material/Default-Skin |
| **5 Migration & Release** | Übergangs-Image, Migrations-Assistent, Beta mit Händlern/Bestandskunden, Doku, Browser-Demo | 100 % der Test-Altgeräte migriert ohne Datenverlust; Stromausfall-Tests während der Migration |

Phase 2 und 3 können teilweise parallel laufen (Simulator), sobald die API aus Phase 2 steht.

---

## 10. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Spotify: librespot bekommt keinen Schlüssel mehr, Soloist braucht pro Nutzer einen Developer-Key und läuft nach 90 Tagen ab | Spotify-Partnerprogramm beantragen (lange Vorlaufzeit, früh starten). Bis dahin Soloist mit Auto-Update wie in Tapedeck. |
| Soloist läuft nicht unter Buildroot | Phase-0-Spike; Notfalls Container-ähnliche glibc-Laufzeit für dieses eine Binary |
| Migration beschädigt Karten | Nichts überschreiben bis zum Schluss, Umschalten als letzter atomarer Schritt, Backup auf FAT, viele Stromausfall-Tests |
| Raumkorrektur klingt schlechter als vorher | Konservative Grenzen (vor allem Absenkungen, ≤ +3 dB), Kontrollmessung, A/B, jederzeit aus |
| Android-Installation ohne HTTPS nur als Verknüpfung | Lokales HTTPS (6.2) |
| Pi 3 zu schwach für lange FIR bei 192 kHz | Grenzen pro Plattform messen, Assistent wählt passend (PEQ/kürzere FIR) |

---

## 11. Entscheidungen und offene Fragen

**Entschieden (14.11.2026):**
- Pi 2 fällt weg. Unterstützt werden **alle Aroio-Modelle (SU, EX, LT, AroioOS auf normalem Pi) und Pi 3B, 4, 5**.
- **Partnerprogramme für Spotify Connect, TIDAL Connect und Qobuz Connect werden angefragt.** Bis zur Zusage: Spotify über Soloist/go-librespot, TIDAL/Qobuz über die Lyrion-Plugins (4.5a).
- Lyrion bleibt. Neue Player- und Bibliotheksansicht in der PWA (4.5).
- **Zertifikatsdienst (HTTPS) kommt später.** Erst wird entwickelt; Themen für den Produktivbetrieb werden vor dem Release geklärt. Die App läuft mit und ohne HTTPS.
- **Neubau in neuem Ordner/Repo `aroio`** neben `aroio-ng`; `aroio-ng` bleibt unverändert.
- **Einstellungen:** `config.json` mit Schema und Versionsnummer, Geheimnisse getrennt in `secrets.json` (0600), atomares Schreiben, ein Schreiber (aroiod). `userconfig.txt` wird nur bei der Migration gelesen.
- **Simulator** nach Tapedeck-Muster, mit Umschalter Mobil/Tablet/Desktop/Querformat/beides nebeneinander, Ton am Rechner und Raumeinmessung (echtes UMIK am Rechner oder vollständig simuliert).
- **Cleaner** = M/S-Codierung des Stereosignals (Hilfetext angepasst).
- **Modelleigenschaften SU/EX/LT** in `aroiod/models.py` gelten vorerst als richtig, Anpassung bei Bedarf.
- **Erste echte Hardware:** Raspberry Pi mit IQaudio-DAC (Pi DAC+/DAC Pro/DigiAMP+).

**Vor dem Produktivbetrieb zu klären:**
1. Domain und Betrieb des Zertifikatsdienstes.
2. Nutzung der Lyrion-Plugins für TIDAL/Qobuz im kommerziellen Produkt (Plugin-Autoren, Dienste), bis die Partnerprogramme zusagen.
3. Raumkorrektur: Acourate/Audiovero-Weg gleichrangig oder nur im Expertenmodus? Vorgaben von Audiovero?
4. NetJack und Eingang: noch genutzt? (NetJack ist im Neubau bisher gestrichen.)
5. Zugangsschutz der App: ohne Passwort im Heimnetz oder optional mit Passwort (wie `USERPASSWD`)?
6. Erkennung der Modelle per HAT-EEPROM oder I²C (Eigenschaften SU/EX/LT vorerst bestätigt, siehe unten).

---

## 12. Stand der Umsetzung (14.11.2026)

**Fertig und getestet (im Simulator):**
- `aroiod`: Konfiguration mit Schema, Geheimnisse, Wiedergabe mit Warteschlange, Quellen-Umschaltung, Lautstärke (fester Pegel bei SU/EX), Abtastrate folgt der Quelle, CamillaDSP-Konfiguration (PEQ, FIR, Cleaner, Resampling, Bitgenau-Erkennung), FIR-Import (.dbl/.wav), Presets, Raumkorrektur (Algorithmus + Assistent + A/B), Migration aus `userconfig.txt` inkl. Filterbänke, Dienste-Anmeldung (simuliert), Netzwerk, Bluetooth, Updates, Neustart, Werkseinstellungen, Diagnose-Paket.
- App (Svelte 5 PWA): Start/Player, Warteschlange, Musik (Übersicht, Bereiche, Album, Künstler, Suche über alle Anbieter), Klang, Raumkorrektur-Stepper, Preset-Details mit Frequenzgang, FIR-Import, Einstellungen (Allgemein, Netzwerk, Dienste inkl. Spotify/TIDAL/Qobuz/Lyrion, Bluetooth, Updates, Gerät), Expertenmodus (Ton, Hardware, System), Einrichtungs-Assistent, Migrations-Assistent, Deutsch/Englisch, hell/dunkel.
- Simulator mit Geräteumschalter und simulierter Hardware/Außenwelt.
- Tests: 38 Backend-Tests; 12 Playwright-Tests (alle Seiten axe-geprüft nach WCAG 2.2 AA, hell und dunkel, 375 px und 1280 px, kein horizontales Scrollen, Einrichtung, Wiedergabe, Raumkorrektur, Migration).

**Entwurf, noch nicht gebaut:** `br2-external/` (Defconfig, Partitionen, RAUC, systemd-Units, Pakete camilladsp/aroiod/aroio-web). Kernel-Commit, Versionen und Hashes werden in Phase 0 festgelegt; der Aroio-DAC-Treiber muss auf Kernel 6.12 portiert werden.

**Nächste Schritte:**
1. Phase 0 auf echter Hardware: Startzeit Altsystem, Buildroot-Minimalimage, DAC-Treiber-Port, CamillaDSP-Ratenwechsel, Soloist unter Buildroot, Lyrion-ARM-Archiv auf Buildroot-Perl, Partitionen echter Altgeräte.
2. Echte `World`-Implementierung (gleiche Schnittstelle wie `sim.SimWorld`): CamillaDSP-WebSocket, Lyrion JSON-RPC/Comet (`LyrionLibrary` mit dem Modell aus `library.py`), BlueZ/iwd über D-Bus, RAUC, evdev für Drehgeber/IR, ALSA-Messung für die Raumkorrektur.
3. Fehlermeldungen des Servers als Codes, damit sie in der englischen App übersetzt erscheinen (heute deutscher Text).
4. Hardware-Belegung anlernen (Tasten, IR) im Expertenmodus.
