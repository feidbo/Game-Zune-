"""Album covers from the internet, for albums whose files brought none.

The Pixel 2 has no Wi-Fi, so the computer looks covers up. Each album folder
on the card without a picture is tried in three passes, stopping at the
first that finds one:

  exact     Deezer, then iTunes, asked for the artist and album; taken only
            when both come back as asked (case, accents and punctuation
            aside).
  close     asked more loosely, and taken when the artist is the one asked
            for and the album near enough: "The Bends" finds "The Bends
            (Collector's Edition)", "Abbey Road - 2019 Mix" finds "Abbey
            Road".
  by song   for an album that is not found, or has no name ("Unknown
            Album", songs straight in an artist's folder): the album one of
            its songs is on, by the song's title and artist.

Neither service needs a key. The cover goes in the folder as cover.jpg, which
is the name the Pixel 2 looks for (src/muselib.c, ml_folder_image), at 500px.
"""
import io
import json
import time
import urllib.parse
import urllib.request

from .match import loose, plain, same_artist, similar

UA = "GameZune/1.0 ( https://github.com/feidbo/Game-Zune- )"
SIDE = 500
CLOSE = 0.75             # how alike an album's name must be for "close"
SONG_CLOSE = 0.8         # and a song's, for "by song"
NO_ALBUM = {"", "unknown album", "unknown", "singles", "(singles)", "untitled"}
VARIOUS = {"various artists", "various", "va", "soundtrack", "compilation"}

DEEZER = "https://api.deezer.com/"
ITUNES = "https://itunes.apple.com/search"


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


class Finder:
    """One run's lookups: the network (`get`, replaceable for tests), each
    service's pace, and the answers so far, so twenty songs of one album ask
    once."""

    def __init__(self, get=None, pace=True):
        self.get = get or _get
        self.pace = pace
        self.last = {}
        self.cache = {}

    def _json(self, service, url, gap):
        if url in self.cache:
            return self.cache[url]
        if self.pace:
            wait = self.last.get(service, 0) + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last[service] = time.monotonic()
        raw = self.get(url)
        try:
            out = json.loads(raw.decode("utf-8")) if raw else None
        except (ValueError, UnicodeDecodeError):
            out = None
        self.cache[url] = out
        return out

    # ---- what the services say ----
    # Each gives [(album, artist, picture url)] for albums, and the same
    # for the albums songs are on.

    def deezer_albums(self, q):
        d = self._json("deezer", DEEZER + "search/album?" + urllib.parse.urlencode({"q": q, "limit": 25}), 0.12)
        return [(a.get("title", ""), (a.get("artist") or {}).get("name", ""),
                 a.get("cover_xl") or a.get("cover_big") or "")
                for a in (d or {}).get("data", []) if isinstance(a, dict)]

    def deezer_songs(self, q):
        d = self._json("deezer", DEEZER + "search?" + urllib.parse.urlencode({"q": q, "limit": 25}), 0.12)
        out = []
        for t in (d or {}).get("data", []):
            if isinstance(t, dict):
                al = t.get("album") or {}
                out.append((t.get("title", ""), (t.get("artist") or {}).get("name", ""),
                            al.get("cover_xl") or al.get("cover_big") or ""))
        return out

    def itunes(self, term, entity):
        # iTunes asks for about twenty searches a minute: one every three
        # seconds, and only when Deezer had nothing.
        d = self._json("itunes", ITUNES + "?" + urllib.parse.urlencode(
            {"term": term, "entity": entity, "limit": 25, "media": "music"}), 3.0)
        name = "collectionName" if entity == "album" else "trackName"
        return [(r.get(name, ""), r.get("artistName", ""),
                 (r.get("artworkUrl100") or "").replace("100x100bb", "600x600bb"))
                for r in (d or {}).get("results", []) if isinstance(r, dict)]

    # ---- the passes ----

    def exact(self, artist, album):
        various = plain(artist) in VARIOUS
        for found in (self.deezer_albums('artist:"%s" album:"%s"' % (artist, album) if not various
                                         else 'album:"%s"' % album),
                      self.itunes("%s %s" % ("" if various else artist, album), "album")):
            for name, who, pic in found:
                if pic and plain(name) == plain(album) and (various or plain(who) == plain(artist)):
                    return pic
        return None

    def close(self, artist, album):
        various = plain(artist) in VARIOUS
        want = loose(album)
        if not want:
            return None
        best, score = None, 0.0
        for found in (self.deezer_albums("%s %s" % ("" if various else loose(artist), want)),
                      self.deezer_albums(want),
                      self.itunes("%s %s" % ("" if various else loose(artist), want), "album")):
            for name, who, pic in found:
                if not pic or not (various or same_artist(artist, who)):
                    continue
                sc = similar(want, loose(name))
                if sc >= CLOSE and sc > score:
                    best, score = pic, sc
            if score >= 0.99:
                break
        return best

    def by_song(self, artist, titles):
        if plain(artist) in VARIOUS:
            artist = ""
        for title in titles[:3]:
            want = loose(title)
            if not want:
                continue
            for found in (self.deezer_songs('artist:"%s" track:"%s"' % (artist, title) if artist
                                            else 'track:"%s"' % title),
                          self.deezer_songs("%s %s" % (loose(artist), want)),
                          self.itunes("%s %s" % (artist, title), "song")):
                for name, who, pic in found:
                    if pic and (not artist or same_artist(artist, who)) and \
                            similar(want, loose(name)) >= SONG_CLOSE:
                        return pic
        return None

    def find(self, artist, album, titles=()):
        """(picture url, how) for an album - how being "exact", "close" or
        "by song" - or (None, None)."""
        named = plain(album) not in NO_ALBUM and plain(album) != plain(artist)
        if named:
            pic = self.exact(artist, album)
            if pic:
                return pic, "exact"
            pic = self.close(artist, album)
            if pic:
                return pic, "close"
        pic = self.by_song(artist, list(titles))
        return (pic, "by song") if pic else (None, None)

    def picture(self, url):
        """A cover as JPEG bytes no bigger than SIDE, or None."""
        data = self.get(url) if url else None
        if not data or not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"):
            return None
        return shrink(data)


def shrink(data):
    try:
        from PIL import Image
    except ImportError:
        return data
    try:
        im = Image.open(io.BytesIO(data))
        im = im.convert("RGB")
        if max(im.size) > SIDE:
            im.thumbnail((SIDE, SIDE))
        b = io.BytesIO()
        im.save(b, "JPEG", quality=90)
        return b.getvalue()
    except Exception:
        return data
