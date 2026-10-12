#!/usr/bin/env python3
"""zunesync - prepare a TortOS card's music the way the Zune software did.

Run on your computer with the card plugged in:

    python3 scripts/zunesync.py /Volumes/TORTOS

It reads every song's tags, looks each one up in public music databases,
and writes to the card:

  Music/.zune/library.tsv   what the Pixel 2's Zune theme shows: real titles,
                            genres, years, lengths (the genres pivot, years
                            on albums, times on tracks, smart dj)
  Playlists/<name>.m3u8     nine auto playlists, each with a cover:

    chill           soft, slow songs - and not slow-jam R&B
    workout         the highest-BPM songs, building up
    dark wave       darkwave, synth-pop, new wave, post-punk - the 80s sound
    nostalgia       songs first released 1998-2010 (no classical, jazz or
                    instrumentals), the best known first
    jazzy           jazz in all its kinds
    party           europop and eurodance
    crowd pleaser   songs that reached the Billboard Hot 100 top 50
    heavy rotation  your most played (counted on the Pixel 2, and Last.fm)
    discover        what you play least and the world knows least

Where the facts come from (all free, all public):

  MusicBrainz     first-release year, genres and tags        no key
  ListenBrainz    how many people listen to a song           no key
  Deezer          tempo (BPM), popularity, release date      no key
  Billboard       Hot 100 chart history, via the public
                  utdata/rwd-billboard-data archive          no key
  Last.fm         mood/vibe tags, your own play counts       free key, optional
                  (https://www.last.fm/api/account/create)
  the Pixel 2     what you played and liked on it (Music/.zune/plays.log
                  and ratings.tsv, written by the device)

Everything looked up is cached in Music/.zune/lookup.json, so only new songs
are looked up next time. MusicBrainz allows one request a second, so a first
run takes about a second or two per song; after that it is quick.

When a song's tempo is not in its tags or on Deezer, and librosa is
installed, a minute of the song is listened to for its tempo and loudness.
That is the only listening done: genres, eras and popularity come from the
databases, not from guessing at the sound.

Only playlists this script wrote are ever replaced. Songs you gave a broken
heart on the Pixel 2 are left out of all of them.

    --lastfm-key KEY    add Last.fm's tags (the best source for "vibe")
    --lastfm-user NAME  count your Last.fm scrobbles in heavy rotation
    --offline           use only what is cached
    --no-listen         never analyse audio
    --size N            songs per playlist (50)
    --only a,b          just these playlists
    --fix-playlists     repoint your own .m3u files at the card's copies
    --dry-run           say what would be written

Needs: pip install mutagen pillow   (librosa optional; ffmpeg for m4a/opus)
"""

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

AUDIO = {".mp3", ".m4a", ".m4b", ".mp4", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wav"}
MARK = "# made by Game Zune zunesync - rerunning it replaces this file"
OLD_MARKS = ("# made by Game Zune moodlists",)
HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "..", "tortos-zune", "fonts", "zune-light.ttf")
UA = "GameZune/1.0 ( https://github.com/feidbo/Game-Zune- )"
BILLBOARD_URL = ("https://raw.githubusercontent.com/utdata/rwd-billboard-data/"
                 "main/data-out/hot-100-current.csv")
CACHE_VERSION = 1

PLAYLISTS = ["chill", "workout", "dark wave", "nostalgia", "jazzy", "party",
             "crowd pleaser", "heavy rotation", "discover"]
COLORS = {
    "chill": (64, 160, 168), "workout": (236, 0, 140), "dark wave": (72, 40, 120),
    "nostalgia": (232, 140, 40), "jazzy": (176, 120, 56), "party": (0, 150, 240),
    "crowd pleaser": (220, 40, 40), "heavy rotation": (120, 180, 40),
    "discover": (40, 120, 200),
}


# ---- names ---------------------------------------------------------------------

def fold(s):
    """Lowercase, accents off, punctuation to spaces: for comparing names."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_title(t):
    """A title without what charts and stores add to it."""
    t = re.sub(r"\s*[\(\[][^\)\]]*(feat|ft\.|with|remaster|version|edit|mix|live|mono|stereo)"
               r"[^\)\]]*[\)\]]", "", t or "", flags=re.I)
    t = re.sub(r"\s+-\s+(\d{4} )?(remaster|single|radio|album|mono|stereo|live).*$", "", t, flags=re.I)
    t = re.sub(r"\s+(feat\.?|ft\.?|featuring)\s.*$", "", t, flags=re.I)
    return fold(t)


def bare_title(t):
    """A title with every bracketed part gone: "We Like To Party! (The
    Vengabus)" and "We Like to Party!" are one song on a chart."""
    return fold(re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", t or ""))


def main_artist(a):
    """The first-named artist: "Drake Featuring Rihanna" is Drake."""
    a = re.split(r"\s+(?:feat\.?|ft\.?|featuring|with|x|vs\.?)\s+|\s*[,;/&]\s*|\s+and\s+",
                 a or "", maxsplit=1, flags=re.I)[0]
    return fold(re.sub(r"^the\s+", "", a.strip(), flags=re.I))


def tag_key(t):
    """One spelling for a tag: "Synth-Pop", "synth pop" and "synthpop" agree."""
    return re.sub(r"[^a-z0-9&]+", "", (t or "").lower().replace("rhythm and blues", "rnb")
                  .replace("r&b", "rnb"))


def tagset(tags):
    return {tag_key(t) for t in tags if t}


# ---- the card ------------------------------------------------------------------

def songs_on(card):
    music = os.path.join(card, "Music")
    for root, dirs, files in os.walk(music):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for f in sorted(files):
            if not f.startswith(".") and os.path.splitext(f)[1].lower() in AUDIO:
                full = os.path.join(root, f)
                yield os.path.relpath(full, card).replace(os.sep, "/"), full


def read_tags(rel, full):
    """What the file says about itself, with the folders standing in."""
    parts = rel.split("/")
    out = {
        "artist": parts[1] if len(parts) >= 4 else (parts[1] if len(parts) == 3 else ""),
        "album": parts[2] if len(parts) >= 4 else (parts[1] if len(parts) == 3 else ""),
        "title": re.sub(r"^\d+[\s.\-_]*", "", os.path.splitext(parts[-1])[0]),
        "genre": [], "year": 0, "num": 0, "secs": 0, "bpm": 0, "mood": "", "mbid": "",
    }
    try:
        import mutagen
        f = mutagen.File(full, easy=True)
    except Exception:
        f = None
    if f is None:
        return out
    if getattr(f, "info", None) is not None:
        out["secs"] = int(getattr(f.info, "length", 0) or 0)

    def first(*keys):
        for k in keys:
            try:
                v = f.get(k)
            except Exception:
                v = None
            if v:
                return str(v[0] if isinstance(v, list) else v)
        return ""

    out["title"] = first("title") or out["title"]
    out["artist"] = first("artist", "albumartist") or out["artist"]
    out["album"] = first("album") or out["album"]
    try:
        out["genre"] = [g for v in (f.get("genre") or []) for g in re.split(r"[;/]", str(v)) if g.strip()]
    except Exception:
        pass
    m = re.match(r"(\d{4})", first("originaldate", "date", "year"))
    out["year"] = int(m.group(1)) if m else 0
    m = re.match(r"(\d+)", first("tracknumber"))
    out["num"] = int(m.group(1)) if m else 0
    try:
        out["bpm"] = int(round(float(first("bpm") or 0)))
    except ValueError:
        pass
    out["mood"] = first("mood")
    out["mbid"] = first("musicbrainz_trackid")
    return out


def read_device(card):
    """Plays and ratings the Pixel 2 kept."""
    plays, last, rating = {}, {}, {}
    z = os.path.join(card, "Music", ".zune")
    try:
        with open(os.path.join(z, "plays.log"), encoding="utf-8", errors="replace") as f:
            for line in f:
                t, _, path = line.rstrip("\r\n").partition("\t")
                if path:
                    plays[path] = plays.get(path, 0) + 1
                    last[path] = max(last.get(path, 0), int(t or 0))
    except OSError:
        pass
    try:
        with open(os.path.join(z, "ratings.tsv"), encoding="utf-8", errors="replace") as f:
            for line in f:
                path, _, v = line.rstrip("\r\n").partition("\t")
                if path and v.strip():
                    rating[path] = 1 if int(v) > 0 else -1 if int(v) < 0 else 0
    except (OSError, ValueError):
        pass
    return plays, last, rating


# ---- the web -------------------------------------------------------------------

class Net:
    """HTTP with each service's manners: MusicBrainz one request a second,
    the others a little faster, and everything tried twice."""

    def __init__(self, offline=False):
        self.offline = offline
        self.last = {}
        self.failures = {}

    def _wait(self, host, gap):
        t = self.last.get(host, 0) + gap - time.time()
        if t > 0:
            time.sleep(t)
        self.last[host] = time.time()

    def json(self, url, params=None, gap=0.2, body=None):
        if self.offline:
            return None
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        host = urllib.parse.urlparse(url).netloc
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(3):
            self._wait(host, gap)
            req = urllib.request.Request(url, data=data, headers={
                "User-Agent": UA, "Accept": "application/json",
                **({"Content-Type": "application/json"} if data else {})})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < 2:
                    time.sleep(2 + attempt * 3)
                    continue
                if e.code == 404:
                    return None
                self.failures[host] = self.failures.get(host, 0) + 1
                return None
            except (urllib.error.URLError, TimeoutError, ValueError, OSError):
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                self.failures[host] = self.failures.get(host, 0) + 1
                return None
        return None

    def download(self, url, out):
        if self.offline:
            return False
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=120) as r, open(out + ".part", "wb") as f:
                while True:
                    b = r.read(1 << 16)
                    if not b:
                        break
                    f.write(b)
            os.replace(out + ".part", out)
            return True
        except (urllib.error.URLError, OSError):
            return False


def mb_pick(recs, title, artist, secs):
    """The search result that is this song, or None - with the earliest
    first-release year of every result that is it, since the same song is
    on many records and the first of them is when it came out."""
    want_t, want_a = clean_title(title), main_artist(artist)
    best, best_s, years = None, 0, []
    for r in recs or []:
        s = int(r.get("score", 0))
        if clean_title(r.get("title", "")) != want_t:
            continue
        credit = " ".join(c.get("name", "") + c.get("joinphrase", "") for c in r.get("artist-credit", []))
        if main_artist(credit) != want_a and want_a not in fold(credit):
            continue
        if secs and r.get("length") and abs(r["length"] / 1000 - secs) > 20:
            s -= 30
        # Prefer the recording first released earliest: the original, not
        # a compilation's copy of it.
        if r.get("first-release-date"):
            s += 5
        if s >= 70:
            m = re.match(r"(\d{4})", r.get("first-release-date") or "")
            if m:
                years.append(int(m.group(1)))
        if s > best_s:
            best, best_s = r, s
    if best_s < 70:
        return None
    best = dict(best)
    if years:
        best["first-release-date"] = str(min(years))
    return best


def lookup_musicbrainz(net, cache, key, t):
    c = cache["mb"].get(key)
    if c is not None:
        return c
    rec = None
    if t["mbid"]:
        rec = net.json("https://musicbrainz.org/ws/2/recording/" + t["mbid"],
                       {"inc": "tags+genres+artist-credits", "fmt": "json"}, gap=1.1)
    if rec is None:
        q = 'recording:"%s" AND artist:"%s"' % (t["title"].replace('"', ""), t["artist"].replace('"', ""))
        res = net.json("https://musicbrainz.org/ws/2/recording",
                       {"query": q, "fmt": "json", "limit": 8}, gap=1.1)
        if res is None:
            return None                       # not cached: try again next run
        rec = mb_pick(res.get("recordings"), t["title"], t["artist"], t["secs"])
    out = {"id": "", "year": 0, "tags": [], "artist_id": ""}
    if rec:
        out["id"] = rec.get("id", "")
        m = re.match(r"(\d{4})", rec.get("first-release-date") or "")
        out["year"] = int(m.group(1)) if m else 0
        out["tags"] = [g["name"] for g in (rec.get("genres") or []) + (rec.get("tags") or [])
                       if g.get("count", 1) >= 1]
        credit = rec.get("artist-credit") or []
        if credit and isinstance(credit[0], dict) and credit[0].get("artist"):
            out["artist_id"] = credit[0]["artist"].get("id", "")
    cache["mb"][key] = out
    return out


def lookup_mb_artist(net, cache, aid):
    if not aid:
        return []
    if aid in cache["mb_artist"]:
        return cache["mb_artist"][aid]
    res = net.json("https://musicbrainz.org/ws/2/artist/" + aid,
                   {"inc": "genres+tags", "fmt": "json"}, gap=1.1)
    if res is None:
        return []
    tags = [g["name"] for g in sorted((res.get("genres") or []) + (res.get("tags") or []),
                                      key=lambda g: -g.get("count", 0))[:12]]
    cache["mb_artist"][aid] = tags
    return tags


def lookup_listenbrainz(net, cache, mbids):
    todo = [m for m in mbids if m and m not in cache["lb"]]
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        res = net.json("https://api.listenbrainz.org/1/popularity/recording",
                       body={"recording_mbids": batch}, gap=0.5)
        if not isinstance(res, list):
            continue
        for row in res:
            m = row.get("recording_mbid")
            if m:
                cache["lb"][m] = {"listens": row.get("total_listen_count") or 0,
                                  "users": row.get("total_user_count") or 0}


def lookup_deezer(net, cache, key, t):
    c = cache["dz"].get(key)
    if c is not None:
        return c
    q = 'artist:"%s" track:"%s"' % (t["artist"].replace('"', ""), t["title"].replace('"', ""))
    res = net.json("https://api.deezer.com/search", {"q": q, "limit": 5}, gap=0.15)
    if res is None or "error" in res:
        return None
    out = {"rank": 0, "bpm": 0, "year": 0}
    want_t, want_a = clean_title(t["title"]), main_artist(t["artist"])
    for d in res.get("data") or []:
        if clean_title(d.get("title", "")) == want_t and \
           main_artist((d.get("artist") or {}).get("name", "")) == want_a:
            out["rank"] = int(d.get("rank") or 0)
            tr = net.json("https://api.deezer.com/track/%s" % d["id"], gap=0.15) or {}
            out["bpm"] = int(round(float(tr.get("bpm") or 0)))
            m = re.match(r"(\d{4})", tr.get("release_date") or "")
            out["year"] = int(m.group(1)) if m else 0
            break
    cache["dz"][key] = out
    return out


def lookup_lastfm(net, cache, key, t, api_key):
    if not api_key:
        return None
    c = cache["lf"].get(key)
    if c is not None:
        return c
    res = net.json("https://ws.audioscrobbler.com/2.0/", {
        "method": "track.gettoptags", "artist": t["artist"], "track": t["title"],
        "autocorrect": 1, "api_key": api_key, "format": "json"}, gap=0.25)
    if res is None or "error" in res:
        return None
    tags = [x["name"] for x in ((res.get("toptags") or {}).get("tag") or [])
            if int(x.get("count", 0)) >= 8][:15]
    cache["lf"][key] = tags
    return tags


def lastfm_user_plays(net, api_key, user):
    """Your Last.fm scrobbles: (artist, title) -> plays."""
    out = {}
    if not (api_key and user):
        return out
    for page in range(1, 11):
        res = net.json("https://ws.audioscrobbler.com/2.0/", {
            "method": "user.gettoptracks", "user": user, "period": "overall", "limit": 1000,
            "page": page, "api_key": api_key, "format": "json"}, gap=0.25)
        tracks = ((res or {}).get("toptracks") or {}).get("track") or []
        for tr in tracks:
            k = (main_artist((tr.get("artist") or {}).get("name", "")), clean_title(tr.get("name", "")))
            out[k] = out.get(k, 0) + int(tr.get("playcount") or 0)
        attr = ((res or {}).get("toptracks") or {}).get("@attr") or {}
        if page >= int(attr.get("totalPages") or 1):
            break
    return out


def billboard(net, zdir):
    """(main artist, title) -> (best peak, weeks on chart), from the Hot 100."""
    path = os.path.join(zdir, "hot100.csv")
    fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < 30 * 86400
    if not fresh and not net.download(BILLBOARD_URL, path) and not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        for row in csv.DictReader(f):
            try:
                peak = int(row.get("peak_pos") or row.get("current_week") or 101)
                weeks = int(row.get("wks_on_chart") or 0)
            except ValueError:
                continue
            a = main_artist(row.get("performer", ""))
            for k in {(a, clean_title(row.get("title", ""))), (a, bare_title(row.get("title", "")))}:
                p, w = out.get(k, (101, 0))
                out[k] = (min(p, peak), max(w, weeks))
    return out


# ---- listening (only for tempo, only when nothing else knows it) -----------------

def listen(full, secs):
    import warnings
    warnings.filterwarnings("ignore")
    import numpy as np
    import librosa
    off = min(45.0, secs * 0.25) if secs > 90 else 0.0
    y, sr = librosa.load(full, sr=22050, mono=True, offset=off, duration=60.0)
    if y.size < sr * 5:
        return None
    env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo = float(np.atleast_1d(librosa.feature.tempo(onset_envelope=env, sr=sr))[0])
    while tempo and tempo < 70:
        tempo *= 2
    while tempo > 190:
        tempo /= 2
    rms = float(20 * np.log10(np.mean(librosa.feature.rms(y=y)[0]) + 1e-6))
    return {"bpm": int(round(tempo)), "loud": rms}


# ---- the playlists ---------------------------------------------------------------

def has(T, words):
    """How strongly a song's tags say `words`: each word's weight, once, for
    a tag that is it or (for words of four letters or more) contains it -
    so "jazz" counts "smoothjazz" and "goth" counts "gothicrock"."""
    s = 0.0
    for w, wt in words.items():
        k = tag_key(w)
        if any(k == t or (len(k) >= 4 and k in t) for t in T):
            s += wt
    return s


def any_in(T, words):
    """Whether any tag is, or contains, one of `words` (already tag keys)."""
    return any(w == t or (len(w) >= 4 and w in t) for t in T for w in words)


CHILL = {"chill": 1.5, "chillout": 1.5, "mellow": 1.5, "downtempo": 1.2, "ambient": 1, "acoustic": 1,
         "lo-fi": 1.2, "lofi": 1.2, "dream pop": 1, "soft rock": 1, "folk": 0.7, "indie folk": 1,
         "chamber pop": 0.7, "singer-songwriter": 0.7, "easy listening": 1, "calm": 1.2,
         "relaxing": 1.2, "relax": 1.2, "soft": 1, "sleep": 1, "slowcore": 1, "trip hop": 0.8,
         "bossa nova": 0.8, "chillwave": 1.2, "beautiful": 0.5, "peaceful": 1.2}
NOT_CHILL = {"rnb", "contemporaryrnb", "alternativernb", "neosoul", "quietstorm", "slowjams",
             "slowjam", "sexy", "sensual", "newjackswing", "trapsoul", "hiphop", "rap", "trap",
             "metal", "heavymetal", "hardrock", "punk", "hardcore", "edm", "techno", "drumandbass",
             "dubstep", "eurodance", "house", "party", "workout"}
WORKOUT = {"workout": 2, "gym": 2, "running": 1.5, "energetic": 1.5, "pump up": 1.5, "edm": 1,
           "drum and bass": 1, "hard rock": 0.8, "metal": 0.8, "hip hop": 0.6, "trap": 0.8,
           "house": 0.6, "techno": 0.8, "dubstep": 1, "punk": 0.8, "electro": 0.6}
DARKWAVE = {"darkwave": 3, "dark wave": 3, "coldwave": 3, "cold wave": 3, "minimal wave": 3,
            "minimal synth": 3, "ethereal wave": 2.5, "synthpop": 2, "synth-pop": 2,
            "new wave": 2, "post-punk": 2, "gothic rock": 2, "goth": 1.5, "new romantic": 2,
            "futurepop": 1.5, "ebm": 1.5, "electropop": 0.8, "synthwave": 0.8, "industrial": 0.7,
            "80s": 1, "1980s": 1}
NOT_NOSTALGIA = {"classical", "instrumental", "orchestral", "baroque", "opera", "contemporaryclassical",
                 "modernclassical", "romantic", "chamber", "score", "filmscore", "neoclassical"}
JAZZ = {"jazz": 2, "bebop": 2, "bop": 1.5, "hard bop": 2, "swing": 1.5, "big band": 2,
        "bossa nova": 1.5, "cool jazz": 2, "vocal jazz": 2, "smooth jazz": 2, "acid jazz": 2,
        "nu jazz": 2, "jazz fusion": 2, "latin jazz": 2, "free jazz": 2, "post-bop": 2,
        "modal jazz": 2, "jazz funk": 2, "soul jazz": 2, "lounge": 0.7}
EURO = {"eurodance": 3, "euro dance": 3, "europop": 3, "euro pop": 3, "euro-pop": 3,
        "euro house": 3, "eurohouse": 3, "eurobeat": 3, "euro disco": 2.5, "eurodisco": 2.5,
        "italo dance": 3, "italo disco": 2.5, "hands up": 3, "eurotrance": 2.5, "euro trance": 2.5,
        "bubblegum dance": 3, "dance-pop": 1, "dance pop": 1, "dance": 0.7, "electropop": 0.5,
        "disco": 0.5, "party": 0.7, "trance": 0.5}


def build(songs, size, rng):
    """Each playlist's songs, in the order they should play."""
    pool = [s for s in songs if s["rating"] >= 0]           # a broken heart is out
    pops = sorted(s["pop"] for s in pool if s["pop"] is not None)
    plays = sorted(s["plays"] for s in pool)

    def pct(v, vals):
        if v is None or not vals:
            return 0.5
        lo, hi = 0, len(vals)
        while lo < hi:
            mid = (lo + hi) // 2
            if vals[mid] < v:
                lo = mid + 1
            else:
                hi = mid
        return lo / max(1, len(vals) - 1)

    louds = sorted(s["loud"] for s in pool if s["loud"] is not None)
    out = {}

    # chill: soft and slow, not R&B slow jams
    cand = []
    for s in pool:
        T = s["tags"]
        if any_in(T, NOT_CHILL) or (s["bpm"] and s["bpm"] > 112):
            continue
        sc = has(T, CHILL)
        if s["bpm"]:
            sc += 1.0 if s["bpm"] <= 95 else 0.4
        if s["loud"] is not None:
            sc += 1.0 - pct(s["loud"], louds)
        if s["mood_tag"] in ("chill",):
            sc += 5
        if sc >= 1.8:
            cand.append((sc + s["rating"] * 0.3, s))
    out["chill"] = [s for _, s in sorted(cand, key=lambda x: -x[0])[:size]]
    out["chill"].sort(key=lambda s: s["bpm"] or 90)

    # workout: the highest tempos, building up to the fastest
    cand = [(s["bpm"] + 15 * has(s["tags"], WORKOUT) +
             (10 * pct(s["loud"], louds) if s["loud"] is not None else 0) +
             (30 if s["mood_tag"] == "workout" else 0), s)
            for s in pool if s["bpm"] >= 125 or s["mood_tag"] == "workout"]
    cand = [c for c in cand if not any_in(c[1]["tags"], {"ambient", "classical", "jazz"})]
    out["workout"] = sorted((s for _, s in sorted(cand, key=lambda x: -x[0])[:size]),
                            key=lambda s: s["bpm"])

    # dark wave: the 80s synth sound, and the revival of it
    cand = []
    for s in pool:
        sc = has(s["tags"], DARKWAVE)
        y = s["year"]
        if sc <= 0:
            continue
        if 1978 <= y <= 1992:
            sc += 1.5
        elif y >= 1996 and not has(s["tags"], {"darkwave": 1, "coldwave": 1, "minimal wave": 1,
                                                "minimal synth": 1, "post-punk": 1}):
            sc -= 1.0
        if sc >= 2.5:
            cand.append((sc, s))
    out["dark wave"] = [s for _, s in sorted(cand, key=lambda x: -x[0])[:size]]
    rng.shuffle(out["dark wave"])

    # nostalgia: 1998-2010, no classical, jazz or instrumentals, best known first
    cand = []
    for s in pool:
        T = s["tags"]
        if not (1998 <= s["year"] <= 2010):
            continue
        if any_in(T, NOT_NOSTALGIA) or any("jazz" in t for t in T):
            continue
        sc = pct(s["pop"], pops) if s["pop"] is not None else 0.3
        if s["peak"] <= 100:
            sc += 1.0 - s["peak"] / 200
        cand.append((sc, s))
    out["nostalgia"] = sorted((s for _, s in sorted(cand, key=lambda x: -x[0])[:size]),
                              key=lambda s: s["year"])

    # jazzy
    cand = [(has(s["tags"], JAZZ) + (2 if s["mood_tag"] == "jazzy" else 0), s) for s in pool]
    cand = [c for c in cand if c[0] >= 1.5]
    out["jazzy"] = [s for _, s in sorted(cand, key=lambda x: -x[0])[:size]]
    rng.shuffle(out["jazzy"])

    # party: europop dance
    cand = []
    for s in pool:
        sc = has(s["tags"], EURO)
        if s["bpm"] and 115 <= s["bpm"] <= 150:
            sc += 0.5
        if s["mood_tag"] == "party":
            sc += 3
        if sc >= 2.5:
            cand.append((sc, s))
    out["party"] = [s for _, s in sorted(cand, key=lambda x: -x[0])[:size]]
    rng.shuffle(out["party"])

    # crowd pleaser: Billboard Hot 100 top 50, the biggest first
    cand = [s for s in pool if s["peak"] <= 50]
    cand.sort(key=lambda s: (s["peak"], -s["weeks"]))
    out["crowd pleaser"] = cand[:size]

    # heavy rotation: what you play most
    cand = [s for s in pool if s["plays"] + s["lf_plays"] > 0]
    cand.sort(key=lambda s: -(s["plays"] + s["lf_plays"] / 4 + (2 if s["rating"] > 0 else 0)))
    if len(cand) > size:
        cand = cand[:size]
    out["heavy rotation"] = [s for s in cand if s["plays"] + s["lf_plays"] >= 2] or cand[:10]

    # discover: least played, least known
    heavy = {id(s) for s in out["heavy rotation"]}
    cand = [(0.55 * (1 - pct(s["pop"], pops)) + 0.45 * (1 - pct(s["plays"], plays)) +
             rng.random() * 0.1, s) for s in pool if id(s) not in heavy]
    out["discover"] = [s for _, s in sorted(cand, key=lambda x: -x[0])[:size]]
    rng.shuffle(out["discover"])
    return out


# ---- writing ---------------------------------------------------------------------

def ours(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(4096)
        return MARK in head or any(m in head for m in OLD_MARKS)
    except OSError:
        return True


def write_playlist(card, name, songs, dry):
    pdir = os.path.join(card, "Playlists")
    path = os.path.join(pdir, name + ".m3u8")
    if os.path.exists(path) and not ours(path):
        print("  skip %-15s Playlists/%s.m3u8 is yours, not this script's" % (name, name))
        return False
    lines = ["#EXTM3U", MARK]
    for s in songs:
        lines.append("#EXTINF:%d,%s - %s" % (s["secs"] or -1, s["title"], s["artist"]))
        lines.append("../" + s["rel"])
    if not dry:
        os.makedirs(pdir, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    return True


def album_cover(card, rel):
    folder = os.path.dirname(os.path.join(card, rel))
    try:
        for name in os.listdir(folder):
            stem, ext = os.path.splitext(name)
            if ext.lower() in (".jpg", ".jpeg", ".png") and stem.lower() in ("cover", "folder", "front"):
                return os.path.join(folder, name)
    except OSError:
        return None
    parent, album = os.path.split(folder)
    for ext in (".jpg", ".png"):
        p = os.path.join(parent, ".media", album + ext)
        if os.path.exists(p):
            return p
    try:
        import mutagen
        f = mutagen.File(os.path.join(card, rel))
        if f is not None:
            if getattr(f, "pictures", None):
                return f.pictures[0].data
            if f.tags is not None:
                for k in list(f.tags.keys()):
                    if str(k).startswith("APIC"):
                        return f.tags[k].data
                if "covr" in f.tags:
                    return bytes(f.tags["covr"][0])
    except Exception:
        pass
    return None


def write_cover(card, name, songs, color, dry):
    """The Zune way: four of its albums in a square, washed in the
    playlist's color, its name in thin lowercase across the bottom."""
    if dry:
        return
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps
    except ImportError:
        return
    size = 600
    img = Image.new("RGB", (size, size), color)
    seen, pics = set(), []
    for s in songs:
        album = os.path.dirname(s["rel"])
        if album in seen:
            continue
        seen.add(album)
        src = album_cover(card, s["rel"])
        if src is None:
            continue
        try:
            pic = Image.open(io.BytesIO(src) if isinstance(src, bytes) else src).convert("RGB")
            pics.append(ImageOps.fit(pic, (size // 2, size // 2)))
        except Exception:
            continue
        if len(pics) == 4:
            break
    for i, pic in enumerate(pics):
        img.paste(pic, ((i % 2) * size // 2, (i // 2) * size // 2))
    img = Image.blend(img, Image.new("RGB", (size, size), color), 0.55 if pics else 1.0)
    draw = ImageDraw.Draw(img)
    font, pt = ImageFont.load_default(), 132
    while pt >= 48:
        try:
            font = ImageFont.truetype(FONT, pt)
        except OSError:
            break
        if draw.textlength(name, font=font) <= size - 48:
            break
        pt -= 8
    draw.text((24, size - 40 - pt), name, font=font, fill=(255, 255, 255))
    out = os.path.join(card, "Playlists", ".media")
    os.makedirs(out, exist_ok=True)
    img.save(os.path.join(out, name + ".jpg"), quality=90)


def write_index(card, songs, dry):
    """Music/.zune/library.tsv, for the Pixel 2."""
    rows = ["#zune-index 1\tpath\ttitle\tartist\talbum\tgenre\tyear\tseconds\ttrack\tbpm\ttags"]

    def cell(v):
        return str(v).replace("\t", " ").replace("\n", " ").replace("\r", " ")

    for s in songs:
        genre = s["genre"] or (s["tag_names"][0].title() if s["tag_names"] else "")
        rows.append("\t".join(cell(v) for v in (
            s["rel"], s["title"], s["artist"], s["album"], genre, s["year"] or "",
            s["secs"] or "", s["num"] or "", s["bpm"] or "", ",".join(s["tag_names"][:10]))))
    if dry:
        return
    z = os.path.join(card, "Music", ".zune")
    os.makedirs(z, exist_ok=True)
    with open(os.path.join(z, "library.tsv.new"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(rows) + "\n")
    os.replace(os.path.join(z, "library.tsv.new"), os.path.join(z, "library.tsv"))


def fix_playlists(card, dry):
    """Point playlists made on another computer at the card's copies of
    their songs, by file name (and folder, when two share a name)."""
    pdir = os.path.join(card, "Playlists")
    if not os.path.isdir(pdir):
        return
    by_name = {}
    for rel, _ in songs_on(card):
        by_name.setdefault(os.path.basename(rel).lower(), []).append(rel)
    for f in sorted(os.listdir(pdir)):
        path = os.path.join(pdir, f)
        if os.path.splitext(f)[1].lower() not in (".m3u", ".m3u8") or ours(path):
            continue
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            lines = fh.read().splitlines()
        changed = missing = 0
        out = []
        for line in lines:
            s = line.strip()
            if not s or s.startswith("#"):
                out.append(line)
                continue
            norm = s.replace("\\", "/")
            here = norm if os.path.isabs(norm) else os.path.normpath(os.path.join(pdir, norm))
            if os.path.isfile(here):
                out.append(line)
                continue
            parts = norm.split("/")
            cands = by_name.get(parts[-1].lower(), [])
            if len(cands) > 1 and len(parts) > 1:
                cands = [c for c in cands if c.split("/")[-2].lower() == parts[-2].lower()] or cands
            if cands:
                out.append("../" + cands[0])
                changed += 1
            else:
                out.append(line)
                missing += 1
        print("  %-24s %d fixed, %d not on the card" % (f, changed, missing))
        if changed and not dry:
            os.replace(path, path + ".bak")
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(out) + "\n")


# ---- main -------------------------------------------------------------------------

def load_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
        if c.get("version") == CACHE_VERSION:
            for k in ("mb", "mb_artist", "lb", "dz", "lf", "audio"):
                c.setdefault(k, {})
            return c
    except (OSError, ValueError):
        pass
    return {"version": CACHE_VERSION, "mb": {}, "mb_artist": {}, "lb": {}, "dz": {}, "lf": {}, "audio": {}}


def save_cache(path, cache, dry):
    if dry:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".new", "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(path + ".new", path)


def main(argv=None, net=None):
    ap = argparse.ArgumentParser(description="Auto playlists and the library index for a TortOS card.")
    ap.add_argument("card", help="the TORTOS drive, e.g. /Volumes/TORTOS or E:\\")
    ap.add_argument("--lastfm-key", default=os.environ.get("LASTFM_API_KEY", ""))
    ap.add_argument("--lastfm-user", default=os.environ.get("LASTFM_USER", ""))
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--no-listen", action="store_true")
    ap.add_argument("--size", type=int, default=50)
    ap.add_argument("--only", default=",".join(PLAYLISTS))
    ap.add_argument("--fix-playlists", action="store_true")
    ap.add_argument("--no-covers", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    card = os.path.abspath(a.card)
    if not os.path.isdir(os.path.join(card, "Music")):
        sys.exit("no Music folder on %s - is that the TORTOS drive?" % card)
    only = [p.strip() for p in a.only.split(",") if p.strip()]
    bad = [p for p in only if p not in PLAYLISTS]
    if bad:
        sys.exit("unknown playlist %s; they are: %s" % (", ".join(bad), ", ".join(PLAYLISTS)))
    net = net or Net(a.offline)
    zdir = os.path.join(card, "Music", ".zune")
    cache_path = os.path.join(zdir, "lookup.json")
    cache = load_cache(cache_path)

    if a.fix_playlists:
        print("fixing your playlists")
        fix_playlists(card, a.dry_run)

    files = list(songs_on(card))
    print("%d songs on the card" % len(files))
    plays, last, rating = read_device(card)
    print("from the Pixel 2: %d songs played, %d rated" % (len(plays), len(rating)))

    songs = []
    t0 = time.time()
    for i, (rel, full) in enumerate(files):
        t = read_tags(rel, full)
        key = "%s\t%s" % (main_artist(t["artist"]), clean_title(t["title"]))
        mb = lookup_musicbrainz(net, cache, key, t) or {}
        art = lookup_mb_artist(net, cache, mb.get("artist_id", ""))
        dz = lookup_deezer(net, cache, key, t) or {}
        lf = lookup_lastfm(net, cache, key, t, a.lastfm_key) or []
        songs.append(dict(rel=rel, full=full, key=key, t=t, mb=mb, art=art, dz=dz, lf=lf))
        if (i + 1) % 25 == 0 or i + 1 == len(files):
            el = time.time() - t0
            print("  looked up %d of %d (%.0fs)" % (i + 1, len(files), el))
            save_cache(cache_path, cache, a.dry_run)
    lookup_listenbrainz(net, cache, [s["mb"].get("id", "") for s in songs])

    hot = billboard(net, zdir) if not a.dry_run or os.path.exists(os.path.join(zdir, "hot100.csv")) else {}
    print("billboard: %s" % ("%d charted songs known" % len(hot) if hot else "not available"))
    lfu = lastfm_user_plays(net, a.lastfm_key, a.lastfm_user)

    can_listen = not a.no_listen
    if can_listen:
        try:
            import librosa  # noqa: F401
        except ImportError:
            can_listen = False
    listened = 0
    for s in songs:
        t, mb, dz = s["t"], s["mb"], s["dz"]
        names = list(dict.fromkeys(
            [g for g in t["genre"]] + (mb.get("tags") or []) + (s["art"] or []) + (s["lf"] or [])))
        s["tag_names"] = [n.lower() for n in names]
        s["tags"] = tagset(names)
        s["title"], s["artist"], s["album"] = t["title"], t["artist"], t["album"]
        s["genre"] = t["genre"][0] if t["genre"] else ""
        years = [y for y in (mb.get("year"), dz.get("year"), t["year"]) if y and y > 1900]
        s["year"] = mb.get("year") or (min(years) if years else 0)
        s["secs"], s["num"] = t["secs"], t["num"]
        s["bpm"] = t["bpm"] or dz.get("bpm") or 0
        s["loud"] = None
        au = cache["audio"].get(s["rel"])
        if au:
            s["bpm"] = s["bpm"] or au.get("bpm", 0)
            s["loud"] = au.get("loud")
        elif can_listen and not s["bpm"]:
            try:
                au = listen(s["full"], s["secs"])
            except Exception:
                au = None
            if au:
                cache["audio"][s["rel"]] = au
                s["bpm"], s["loud"] = au["bpm"], au["loud"]
                listened += 1
        lb = cache["lb"].get(mb.get("id", "")) if mb.get("id") else None
        if lb and lb.get("users"):
            s["pop"] = math.log10(1 + lb["users"])
        elif dz.get("rank"):
            s["pop"] = math.log10(1 + dz["rank"]) - 1.5   # Deezer ranks run higher
        else:
            s["pop"] = None
        a_t = (main_artist(t["artist"]), clean_title(t["title"]))
        s["peak"], s["weeks"] = hot.get(a_t) or hot.get((a_t[0], bare_title(t["title"])), (101, 0))
        s["plays"] = plays.get(s["rel"], 0)
        s["lf_plays"] = lfu.get(a_t, 0)
        s["rating"] = rating.get(s["rel"], 0)
        mood = fold(t["mood"])
        s["mood_tag"] = next((p for p, words in {
            "chill": ("chill", "calm", "relax", "mellow"), "workout": ("workout", "gym", "energetic"),
            "party": ("party", "dance"), "jazzy": ("jazz",)}.items()
            if any(w in mood for w in words)), "")
    if listened:
        print("listened to %d songs for their tempo" % listened)
    save_cache(cache_path, cache, a.dry_run)
    if net.failures:
        print("note: some lookups failed (%s) - they will be tried again next run" %
              ", ".join("%s x%d" % kv for kv in net.failures.items()))

    write_index(card, songs, a.dry_run)
    print("wrote Music/.zune/library.tsv (%d songs)" % len(songs))

    rng = random.Random(dt.date.today().isoformat())   # discover changes daily
    lists = build(songs, max(5, a.size), rng)
    print("playlists:")
    for name in only:
        chosen = lists.get(name, [])
        if len(chosen) < 2:
            print("  %-15s too few songs fit (%d)" % (name, len(chosen)))
            continue
        if write_playlist(card, name, chosen, a.dry_run):
            if not a.no_covers:
                write_cover(card, name, chosen, COLORS[name], a.dry_run)
            print("  %-15s %d songs" % (name, len(chosen)))
    print("done. On the Pixel 2: music, then right to the playlists pivot.")
    return lists


if __name__ == "__main__":
    main()
