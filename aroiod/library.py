"""Music library: one browse model for Lyrion (own music), TIDAL, Qobuz, radio.

The app only knows this generic model, so the views stay the same whether the
data comes from the customer's Lyrion server, the Lyrion on the Aroio or the
Lyrion TIDAL/Qobuz plugins.

    page  = {title, layout: list|grid|album|home, header?, sections?, items?}
    item  = {id, kind, title, subtitle?, image?, duration?, quality?, path?, playable}

IDs: "<provider>:<kind>:<key>", provider in local|tidal|qobuz|radio.

SimLibrary is a deterministic fake catalogue for the simulator and tests.
LyrionLibrary (phase 4) maps Lyrion JSON-RPC onto the same model.
"""

import hashlib
import random

PROVIDERS = {"local": "Meine Musik", "tidal": "TIDAL", "qobuz": "Qobuz", "radio": "Radio"}

_FIRST = ["Nordlicht", "Elbe", "Kupfer", "Atlas", "Mira", "Fjord", "Linden", "Salz", "Echo", "Vela",
          "Polar", "Marlen", "Delta", "Ostwind", "Kobalt", "Juna", "Aurel", "Basalt", "Lumen", "Tessa"]
_SECOND = ["Quartett", "Trio", "Ensemble", "Orchester", "Kollektiv", "& die Brandung", "Sound", "Duo",
           "Projekt", "Sinfonietta", "Band", "Chor"]
_WORDS = ["Morgen", "Hafen", "Stille", "Licht", "Wellen", "Nacht", "Glas", "Wind", "Farben", "Weite",
          "Spuren", "Herbst", "Inseln", "Sterne", "Fluss", "Sand", "Zeit", "Raum", "Klang", "Ferne",
          "Blau", "Gold", "Regen", "Feuer", "Eis", "Tag", "Weg", "Traum", "Kreis", "Ruhe"]
_GENRES = ["Jazz", "Klassik", "Pop", "Rock", "Elektronik", "Singer-Songwriter", "Soul", "Ambient", "Folk"]
_QUALITY = [("FLAC", 16, 44100), ("FLAC", 24, 96000), ("FLAC", 24, 192000), ("FLAC", 24, 48000),
            ("DSD", 1, 2822400), ("ALAC", 16, 44100), ("MP3", 0, 44100)]
_STATIONS = ["Klassik Radio Nord", "Jazz Lounge 24", "Hafenwelle", "Deep Ambient FM", "Indie Kurier",
             "Soul Station", "Folk am Abend", "Elektro Nacht", "Radio Leuchtturm", "Weltmusik Direkt"]


def quality_label(codec, bits, rate):
    if codec == "DSD":
        return f"DSD{rate // 44100}"
    if codec == "MP3":
        return "MP3 320"
    return f"{codec} {bits}/{rate / 1000:g}"


def art_url(key):
    return f"/api/v1/art/{key}.svg"


def art_svg(key, label=""):
    h = hashlib.sha1(key.encode()).digest()
    hue1, hue2 = h[0] * 360 // 256, (h[0] * 360 // 256 + 40 + h[1] % 80) % 360
    initials = "".join(w[0] for w in label.split()[:2]).upper() or "♪"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="hsl({hue1} 45% 42%)"/><stop offset="1" stop-color="hsl({hue2} 55% 22%)"/></linearGradient></defs>
<rect width="300" height="300" fill="url(#g)"/>
<circle cx="{150 + h[2] % 90 - 45}" cy="{150 + h[3] % 90 - 45}" r="{60 + h[4] % 70}" fill="hsl({hue2} 60% 70% / .18)"/>
<text x="150" y="172" font-family="system-ui,sans-serif" font-size="64" font-weight="600" text-anchor="middle" fill="#fff" fill-opacity=".9">{initials}</text>
</svg>"""


class Catalog:
    def __init__(self, provider, seed, artists=24, albums=70):
        rng = random.Random(seed)
        self.provider = provider
        self.artists, self.albums, self.tracks = {}, {}, {}
        names = set()
        while len(names) < artists:
            names.add(f"{rng.choice(_FIRST)} {rng.choice(_SECOND)}")
        for i, name in enumerate(sorted(names)):
            self.artists[str(i)] = {"id": str(i), "name": name}
        tid = 0
        for i in range(albums):
            artist = self.artists[str(rng.randrange(artists))]
            title = " ".join(rng.sample(_WORDS, rng.choice([1, 2, 2, 3]))).capitalize()
            codec, bits, rate = rng.choice(_QUALITY[:5] if provider != "local" else _QUALITY)
            if provider == "tidal" and codec == "DSD":
                codec, bits, rate = "FLAC", 24, 96000
            album = {"id": str(i), "title": title, "artist_id": artist["id"], "artist": artist["name"],
                     "year": rng.randrange(1958, 2027), "genre": rng.choice(_GENRES),
                     "format": {"codec": codec, "bits": bits, "rate": rate}, "tracks": [], "added": i}
            for n in range(1, rng.randrange(6, 14)):
                track = {"id": str(tid), "title": " ".join(rng.sample(_WORDS, rng.choice([1, 2, 3]))).capitalize(),
                         "album_id": album["id"], "n": n, "duration": rng.randrange(150, 520)}
                self.tracks[str(tid)] = track
                album["tracks"].append(str(tid))
                tid += 1
            self.albums[str(i)] = album
        self.playlists = {}
        for i in range(6 if provider == "local" else 10):
            tr = rng.sample(list(self.tracks), 12)
            self.playlists[str(i)] = {"id": str(i), "title": (["Abendruhe", "Sonntagmorgen", "Lieblingsstücke",
                                                                 "Für Gäste", "Hörtest", "Neu entdeckt", "Fokus",
                                                                 "Hi-Res Highlights", "Jazz für Kenner",
                                                                 "Klassik Essentials"])[i], "tracks": tr}

    # ── item builders ──
    def _id(self, kind, key):
        return f"{self.provider}:{kind}:{key}"

    def album_item(self, a):
        f = a["format"]
        return {"id": self._id("album", a["id"]), "kind": "album", "title": a["title"],
                "subtitle": f"{a['artist']} · {a['year']}", "image": art_url(self._id("album", a["id"])),
                "quality": quality_label(f["codec"], f["bits"], f["rate"]),
                "hires": f["bits"] >= 24 or f["codec"] == "DSD",
                "path": f"{self.provider}/album/{a['id']}", "playable": True}

    def artist_item(self, a):
        n = sum(1 for al in self.albums.values() if al["artist_id"] == a["id"])
        return {"id": self._id("artist", a["id"]), "kind": "artist", "title": a["name"],
                "subtitle": f"{n} Alben" if n != 1 else "1 Album", "image": art_url(self._id("artist", a["id"])),
                "path": f"{self.provider}/artist/{a['id']}", "playable": True}

    def track_item(self, t, with_album=True):
        a = self.albums[t["album_id"]]
        f = a["format"]
        return {"id": self._id("track", t["id"]), "kind": "track", "title": t["title"],
                "subtitle": f"{a['artist']} · {a['title']}" if with_album else a["artist"],
                "number": t["n"], "duration": t["duration"], "image": art_url(self._id("album", a["id"])),
                "quality": quality_label(f["codec"], f["bits"], f["rate"]), "playable": True}

    def playlist_item(self, p):
        return {"id": self._id("playlist", p["id"]), "kind": "playlist", "title": p["title"],
                "subtitle": f"{len(p['tracks'])} Titel", "image": art_url(self._id("playlist", p["id"])),
                "path": f"{self.provider}/playlist/{p['id']}", "playable": True}

    def track_meta(self, tid):
        t = self.tracks[tid]
        a = self.albums[t["album_id"]]
        return {"id": self._id("track", tid), "title": t["title"], "artist": a["artist"], "album": a["title"],
                "duration": t["duration"], "image": art_url(self._id("album", a["id"])),
                "format": dict(a["format"]), "provider": self.provider}


class SimLibrary:
    def __init__(self, services_logged_in=None):
        self.catalogs = {"local": Catalog("local", 7, 28, 90),
                         "tidal": Catalog("tidal", 11, 30, 80),
                         "qobuz": Catalog("qobuz", 13, 30, 80)}
        self.logged_in = services_logged_in or (lambda provider: provider == "local")
        self.enabled = lambda provider: True
        self.favorites = []
        self.recent = []

    # ── resolving ──
    def track_meta(self, item_id):
        provider, kind, key = item_id.split(":", 2)
        if provider == "radio":
            name = _STATIONS[int(key)]
            return {"id": item_id, "title": name, "artist": "Live-Stream", "album": "", "duration": 0,
                    "image": art_url(item_id), "format": {"codec": "AAC", "bits": 0, "rate": 48000},
                    "provider": "radio", "live": True}
        return self.catalogs[provider].track_meta(key)

    def resolve(self, item_id):
        """Item -> list of track ids to queue."""
        provider, kind, key = item_id.split(":", 2)
        if provider == "radio":
            return [item_id]
        c = self.catalogs[provider]
        if kind == "track":
            return [item_id]
        if kind == "album":
            return [c._id("track", t) for t in c.albums[key]["tracks"]]
        if kind == "artist":
            out = []
            for a in sorted(c.albums.values(), key=lambda a: a["year"]):
                if a["artist_id"] == key:
                    out += [c._id("track", t) for t in a["tracks"]]
            return out
        if kind == "playlist":
            return [c._id("track", t) for t in c.playlists[key]["tracks"]]
        raise KeyError(item_id)

    def remember(self, item_id):
        if ":album:" in item_id or ":playlist:" in item_id or item_id.startswith("radio:"):
            self.recent = [item_id] + [i for i in self.recent if i != item_id]
            self.recent = self.recent[:12]

    def item(self, item_id):
        provider, kind, key = item_id.split(":", 2)
        if provider == "radio":
            return self._station(int(key))
        c = self.catalogs[provider]
        return {"album": lambda: c.album_item(c.albums[key]), "artist": lambda: c.artist_item(c.artists[key]),
                "playlist": lambda: c.playlist_item(c.playlists[key]),
                "track": lambda: c.track_item(c.tracks[key])}[kind]()

    def _station(self, i):
        return {"id": f"radio:station:{i}", "kind": "station", "title": _STATIONS[i],
                "subtitle": "Internetradio", "image": art_url(f"radio:station:{i}"), "playable": True}

    def toggle_favorite(self, item_id):
        if item_id in self.favorites:
            self.favorites.remove(item_id)
            return False
        self.favorites.insert(0, item_id)
        return True

    # ── pages ──
    def home(self):
        loc = self.catalogs["local"]
        sections = []
        if self.recent:
            sections.append({"title": "Zuletzt gehört", "items": [self.item(i) for i in self.recent]})
        newest = sorted(loc.albums.values(), key=lambda a: -a["added"])[:12]
        sections.append({"title": "Neu in deiner Musik", "path": "local/albums",
                         "items": [loc.album_item(a) for a in newest]})
        if self.favorites:
            sections.append({"title": "Favoriten", "path": "favorites",
                             "items": [self.item(i) for i in self.favorites[:12]]})
        for p in ("tidal", "qobuz"):
            if self.enabled(p) and self.logged_in(p):
                c = self.catalogs[p]
                hires = [a for a in c.albums.values() if a["format"]["bits"] >= 24][:10]
                sections.append({"title": f"Hi-Res bei {PROVIDERS[p]}", "path": f"{p}",
                                 "items": [c.album_item(a) for a in hires]})
        sections.append({"title": "Radio", "path": "radio", "items": [self._station(i) for i in range(6)]})
        return {"title": "Musik", "layout": "home", "sections": sections}

    def browse(self, path):
        parts = [p for p in path.strip("/").split("/") if p]
        if not parts:
            return self.home()
        provider = parts[0]
        if provider == "favorites":
            return {"title": "Favoriten", "layout": "list", "items": [self.item(i) for i in self.favorites],
                    "empty": "Noch keine Favoriten. Tippe bei einem Album oder Titel auf das Herz."}
        if provider == "radio":
            return {"title": "Radio", "layout": "list", "items": [self._station(i) for i in range(len(_STATIONS))]}
        if provider not in self.catalogs:
            raise KeyError(path)
        if provider != "local" and not self.enabled(provider):
            return {"title": PROVIDERS[provider], "layout": "list", "items": [], "service": provider,
                    "empty": f"{PROVIDERS[provider]} ist ausgeschaltet. Einschalten unter Einstellungen › Dienste.",
                    "action": {"label": "Zu den Diensten", "route": "/einstellungen/dienste"}}
        if provider != "local" and not self.logged_in(provider):
            return {"title": PROVIDERS[provider], "layout": "list", "items": [], "service": provider,
                    "empty": f"Melde dich bei {PROVIDERS[provider]} an, um die Musik hier zu sehen.",
                    "action": {"label": f"Bei {PROVIDERS[provider]} anmelden", "route": f"/einstellungen/dienste/{provider}"}}
        c = self.catalogs[provider]
        if len(parts) == 1:
            title = PROVIDERS[provider]
            links = [("Künstler", "artists"), ("Alben", "albums"), ("Playlisten", "playlists")]
            if provider == "local":
                links += [("Genres", "genres"), ("Ordner", "folders")]
            else:
                links = [("Neu erschienen", "albums"), ("Meine Playlisten", "playlists"), ("Künstler", "artists")]
            return {"title": title, "layout": "list", "items": [
                {"id": f"{provider}:link:{key}", "kind": "link", "title": label, "path": f"{provider}/{key}",
                 "playable": False} for label, key in links]}
        what = parts[1]
        if what == "artists":
            return {"title": "Künstler", "layout": "list",
                    "items": [c.artist_item(a) for a in sorted(c.artists.values(), key=lambda a: a["name"])]}
        if what == "albums":
            return {"title": "Alben", "layout": "grid",
                    "items": [c.album_item(a) for a in sorted(c.albums.values(), key=lambda a: a["title"])]}
        if what == "playlists":
            return {"title": "Playlisten", "layout": "list",
                    "items": [c.playlist_item(p) for p in c.playlists.values()]}
        if what == "genres":
            genres = sorted({a["genre"] for a in c.albums.values()})
            return {"title": "Genres", "layout": "list", "items": [
                {"id": f"local:genre:{g}", "kind": "genre", "title": g, "path": f"local/genre/{g}",
                 "subtitle": f"{sum(1 for a in c.albums.values() if a['genre'] == g)} Alben", "playable": False}
                for g in genres]}
        if what == "genre":
            g = parts[2]
            return {"title": g, "layout": "grid",
                    "items": [c.album_item(a) for a in c.albums.values() if a["genre"] == g]}
        if what == "folders":
            letters = sorted({a["artist"][0] for a in c.albums.values()})
            if len(parts) == 2:
                return {"title": "Ordner", "layout": "list", "items": [
                    {"id": f"local:folder:{l}", "kind": "folder", "title": l, "path": f"local/folders/{l}",
                     "playable": False} for l in letters]}
            return {"title": parts[2], "layout": "list",
                    "items": [c.album_item(a) for a in c.albums.values() if a["artist"][0] == parts[2]]}
        if what == "artist":
            a = c.artists[parts[2]]
            albums = sorted((al for al in c.albums.values() if al["artist_id"] == a["id"]), key=lambda x: -x["year"])
            return {"title": a["name"], "layout": "grid", "header": c.artist_item(a),
                    "items": [c.album_item(al) for al in albums]}
        if what == "album":
            a = c.albums[parts[2]]
            item = c.album_item(a)
            item["favorite"] = item["id"] in self.favorites
            total = sum(c.tracks[t]["duration"] for t in a["tracks"])
            item.update({"artist_path": f"{provider}/artist/{a['artist_id']}", "genre": a["genre"],
                         "year": a["year"], "duration": total, "count": len(a["tracks"])})
            return {"title": a["title"], "layout": "album", "header": item,
                    "items": [c.track_item(c.tracks[t], with_album=False) for t in a["tracks"]]}
        if what == "playlist":
            p = c.playlists[parts[2]]
            item = c.playlist_item(p)
            item["favorite"] = item["id"] in self.favorites
            return {"title": p["title"], "layout": "album", "header": item,
                    "items": [c.track_item(c.tracks[t]) for t in p["tracks"]]}
        raise KeyError(path)

    def search(self, query, scope="all"):
        q = query.strip().lower()
        if len(q) < 2:
            return {"query": query, "groups": []}
        groups = []
        providers = ["local", "tidal", "qobuz"] if scope == "all" else [scope]
        for p in providers:
            if p != "local" and not (self.enabled(p) and self.logged_in(p)):
                continue
            c = self.catalogs[p]
            artists = [c.artist_item(a) for a in c.artists.values() if q in a["name"].lower()][:6]
            albums = [c.album_item(a) for a in c.albums.values()
                      if q in a["title"].lower() or q in a["artist"].lower()][:12]
            tracks = [c.track_item(t) for t in c.tracks.values() if q in t["title"].lower()][:12]
            if artists or albums or tracks:
                groups.append({"provider": p, "title": PROVIDERS[p], "artists": artists,
                               "albums": albums, "tracks": tracks})
        stations = [self._station(i) for i, s in enumerate(_STATIONS) if q in s.lower()]
        if stations and scope in ("all", "radio"):
            groups.append({"provider": "radio", "title": "Radio", "artists": [], "albums": [], "tracks": stations})
        return {"query": query, "groups": groups}
