#!/usr/bin/env python3
"""Mood and vibe playlists for a TortOS card, made on your computer.

Listens to every song in the card's Music folder (a minute of each), works out
how it feels - tempo, energy, brightness, major or minor, how danceable, how
busy - and writes playlists the music player shows under its "playlists" pivot:

    Playlists/chill.m3u8        Playlists/.media/chill.jpg   (its cover)
    Playlists/focus.m3u8        ...
    Playlists/energy.m3u8
    Playlists/happy.m3u8
    Playlists/rainy day.m3u8
    Playlists/late night.m3u8
    Playlists/party.m3u8

Moods are judged against YOUR library, not an absolute scale: "chill" is the
calmest part of what you own, whatever you own.

Tags win over listening. A song tagged with a mood (the MOOD tag, which Mp3tag
and MusicBrainz Picard can set) goes in that playlist whatever it sounds like,
and the GENRE tag nudges the guess.

"Smart DJ" mixes: --mix "name=seed" makes a playlist of the songs that sound
most like the seed, which is an artist, an album or a song title.

    python3 scripts/moodlists.py /Volumes/TORTOS
    python3 scripts/moodlists.py /Volumes/TORTOS --mix "sunday=Boards of Canada"
    python3 scripts/moodlists.py /Volumes/TORTOS --size 30 --moods chill,party

Only playlists this script wrote are ever replaced; your own .m3u files in
Playlists/ are left alone (--fix-playlists repairs their paths for the card).
What it heard is cached in Playlists/.moods/, so a second run only listens to
new songs.

Needs: pip install librosa mutagen pillow   (and ffmpeg for m4a/aac/opus)
"""

import argparse
import hashlib
import json
import math
import os
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed

AUDIO = {".mp3", ".m4a", ".m4b", ".mp4", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wav"}
MARK = "# made by Game Zune moodlists - rerunning it replaces this file"
CACHE_VERSION = 2
HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "..", "tortos-zune", "fonts", "zune-light.ttf")

# ---- the moods -----------------------------------------------------------------
#
# Each is a weighted sum of a song's features as PERCENTILES of the library
# (0 = the least of anything in it, 1 = the most), plus genre words that push
# it up or down. `color` is its cover's.
#
# Features: energy (loudness), tempo, bright (spectral centroid), busy (onsets
# per second), pulse (how clear the beat is), perc (percussive share), major
# (major-key likeness), dance (pulse near 100-130 bpm).

MOODS = {
    "chill": dict(
        w={"energy": -0.35, "tempo": -0.15, "busy": -0.25, "bright": -0.15, "perc": -0.10},
        up=["ambient", "chill", "downtempo", "lo-fi", "lofi", "acoustic", "folk", "dream pop",
            "bossa", "jazz", "new age", "shoegaze", "trip hop", "trip-hop"],
        down=["metal", "punk", "hardcore", "drum and bass", "dubstep", "grindcore"],
        color=(64, 160, 168)),
    "focus": dict(
        w={"busy": -0.30, "energy": -0.10, "pulse": 0.20, "bright": -0.10, "steady": 0.30},
        up=["instrumental", "ambient", "classical", "post-rock", "minimal", "electronic",
            "soundtrack", "score", "piano", "idm", "lo-fi", "lofi"],
        down=["hip hop", "rap", "metal", "punk", "comedy"],
        color=(80, 112, 224)),
    "energy": dict(
        w={"energy": 0.35, "tempo": 0.20, "perc": 0.20, "busy": 0.25},
        up=["rock", "metal", "punk", "edm", "drum and bass", "dnb", "hardcore", "electro",
            "hip hop", "rap", "trap", "dubstep", "techno"],
        down=["ambient", "classical", "folk", "acoustic", "new age"],
        color=(236, 0, 140)),
    "happy": dict(
        w={"major": 0.40, "bright": 0.20, "tempo": 0.20, "energy": 0.10, "dance": 0.10},
        up=["pop", "funk", "disco", "soul", "motown", "reggae", "ska", "indie pop",
            "k-pop", "j-pop", "city pop", "afrobeat"],
        down=["doom", "black metal", "dark", "sad"],
        color=(240, 168, 32)),
    "rainy day": dict(
        w={"major": -0.40, "tempo": -0.20, "bright": -0.20, "energy": -0.20},
        up=["sad", "slowcore", "blues", "emo", "singer-songwriter", "folk", "indie folk",
            "dream pop", "shoegaze", "post-rock"],
        down=["disco", "party", "edm", "funk"],
        color=(96, 104, 136)),
    "late night": dict(
        w={"bright": -0.30, "major": -0.15, "pulse": 0.25, "energy": -0.10, "mid_tempo": 0.20},
        up=["trip hop", "trip-hop", "r&b", "rnb", "neo soul", "jazz", "house", "deep house",
            "synthwave", "darkwave", "chillwave", "downtempo", "lo-fi"],
        down=["country", "bluegrass", "children"],
        color=(112, 56, 200)),
    "party": dict(
        w={"dance": 0.40, "pulse": 0.20, "energy": 0.25, "major": 0.15},
        up=["dance", "house", "disco", "funk", "pop", "hip hop", "rap", "edm", "reggaeton",
            "electro", "club", "dancehall", "afrobeats"],
        down=["ambient", "classical", "folk", "slowcore"],
        color=(255, 96, 32)),
}

# What a MOOD tag can say for each playlist.
MOOD_TAGS = {
    "chill": ["chill", "relaxed", "calm", "mellow", "peaceful", "relaxing"],
    "focus": ["focus", "study", "concentration", "work"],
    "energy": ["energy", "energetic", "workout", "hype", "aggressive", "intense", "pump"],
    "happy": ["happy", "joyful", "uplifting", "cheerful", "sunny", "feel good", "feel-good"],
    "rainy day": ["sad", "melancholy", "melancholic", "rainy", "rainy day", "somber", "blue"],
    "late night": ["late night", "night", "nocturnal", "dark", "moody", "sensual"],
    "party": ["party", "dance", "danceable", "groovy", "club"],
}


# ---- listening -----------------------------------------------------------------

def tags_of(path):
    """artist, title, album, genre, mood, bpm and length from the file's tags."""
    out = {"artist": "", "title": "", "album": "", "genre": "", "mood": "", "bpm": 0.0, "length": 0.0}
    try:
        import mutagen
        f = mutagen.File(path, easy=True)
        if f is None:
            return out
        if getattr(f, "info", None) is not None:
            out["length"] = float(getattr(f.info, "length", 0) or 0)
        for k in ("artist", "title", "album", "genre", "mood"):
            v = f.get(k) if hasattr(f, "get") else None
            if v:
                out[k] = str(v[0]) if isinstance(v, list) else str(v)
        bpm = f.get("bpm") if hasattr(f, "get") else None
        if bpm:
            try:
                out["bpm"] = float(str(bpm[0] if isinstance(bpm, list) else bpm))
            except ValueError:
                pass
        if not out["mood"]:
            # ID3's mood lives in TMOO, or a TXXX:MOOD that easy mode does not map.
            raw = mutagen.File(path)
            if raw is not None and getattr(raw, "tags", None) is not None:
                for key in ("TMOO", "TXXX:MOOD", "TXXX:mood", "----:com.apple.iTunes:MOOD"):
                    if key in raw.tags:
                        v = raw.tags[key]
                        out["mood"] = str(v.text[0] if hasattr(v, "text") else v[0])
                        break
    except Exception:
        pass
    return out


KS_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
KS_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def listen(path):
    """What a minute of the song sounds like, as plain numbers."""
    warnings.filterwarnings("ignore")
    import numpy as np
    import librosa

    tags = tags_of(path)
    length = tags["length"]
    offset = 0.0
    if length > 90:
        offset = min(45.0, length * 0.25)          # past the intro
    y, sr = librosa.load(path, sr=22050, mono=True, offset=offset, duration=60.0)
    if y.size < sr * 5:
        raise ValueError("too short to judge")

    rms = librosa.feature.rms(y=y)[0]
    energy = float(20 * np.log10(np.mean(rms) + 1e-6))
    bright = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    tempo = float(np.atleast_1d(tempo)[0])
    if tags["bpm"] > 30:
        tempo = tags["bpm"]                        # a tagged tempo is a measured one
    while tempo and tempo < 70:
        tempo *= 2
    while tempo > 180:
        tempo /= 2
    # Onsets per second. scipy's peak finder rather than librosa's onset_detect,
    # whose numba kernel crashes on some numba builds.
    from scipy.signal import find_peaks
    env = onset_env / (np.max(onset_env) + 1e-9)
    peaks, _ = find_peaks(env, height=0.1, prominence=0.08, distance=3)
    busy = float(len(peaks) / (y.size / sr))
    pulse = 0.0
    if len(beats) > 4:
        pulse = float(np.mean(onset_env[beats]) / (np.mean(onset_env) + 1e-6))
    # How much the onset strength varies between beats: low is steady.
    steady = float(1.0 / (1.0 + np.std(onset_env) / (np.mean(onset_env) + 1e-6)))
    harm, perc = librosa.effects.hpss(y)
    perc_share = float(np.sum(perc ** 2) / (np.sum(harm ** 2) + np.sum(perc ** 2) + 1e-9))
    chroma = np.mean(librosa.feature.chroma_cqt(y=harm, sr=sr), axis=1)
    best_maj = max(np.corrcoef(chroma, np.roll(KS_MAJOR, k))[0, 1] for k in range(12))
    best_min = max(np.corrcoef(chroma, np.roll(KS_MINOR, k))[0, 1] for k in range(12))
    return {
        "tags": tags,
        "f": {
            "energy": energy, "tempo": tempo, "bright": bright, "busy": busy,
            "pulse": pulse, "steady": steady, "perc": perc_share,
            "major": float(best_maj - best_min),
        },
    }


def _listen_job(args):
    rel, full = args
    try:
        return rel, listen(full), None
    except Exception as e:                       # one bad file is not a failed run
        return rel, None, str(e)


# ---- the card ------------------------------------------------------------------

def songs_on(card):
    music = os.path.join(card, "Music")
    for root, dirs, files in os.walk(music):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for f in sorted(files):
            if not f.startswith(".") and os.path.splitext(f)[1].lower() in AUDIO:
                full = os.path.join(root, f)
                yield os.path.relpath(full, card).replace(os.sep, "/"), full


def load_cache(path):
    try:
        with open(path) as f:
            c = json.load(f)
        return c if c.get("version") == CACHE_VERSION else {"version": CACHE_VERSION, "songs": {}}
    except (OSError, ValueError):
        return {"version": CACHE_VERSION, "songs": {}}


def stamp(full):
    st = os.stat(full)
    return "%d:%d" % (st.st_size, int(st.st_mtime))


# ---- judging -------------------------------------------------------------------

def percentiles(songs, key):
    import bisect
    vals = sorted(s["f"][key] for s in songs)
    n = len(vals)
    return {id(s): bisect.bisect_left(vals, s["f"][key]) / max(1, n - 1) for s in songs}


def derived(s, p):
    """The features as percentiles, plus the two that are shapes not amounts."""
    q = {k: p[k][id(s)] for k in p}
    t = s["f"]["tempo"]
    q["dance"] = max(0.0, 1.0 - abs(t - 120.0) / 40.0) * (0.5 + 0.5 * q["pulse"])
    q["mid_tempo"] = max(0.0, 1.0 - abs(t - 100.0) / 40.0)
    return q


def genre_nudge(genre, mood):
    g = genre.lower()
    m = MOODS[mood]
    nudge = 0.0
    if any(w in g for w in m["up"]):
        nudge += 0.15
    if any(w in g for w in m["down"]):
        nudge -= 0.20
    return nudge


def tagged(mood_tag, mood):
    t = mood_tag.lower()
    return bool(t) and any(w in t for w in MOOD_TAGS[mood])


def score(q, mood):
    w = MOODS[mood]["w"]
    total = sum(abs(v) for v in w.values())
    s = sum((q[k] if v > 0 else 1.0 - q[k]) * abs(v) for k, v in w.items())
    return s / total


def flow(songs, key=None):
    """Order a playlist so it moves rather than jumps: by tempo, and never the
    same artist twice in a row when there is a choice."""
    songs = sorted(songs, key=key or (lambda s: s["f"]["tempo"]))
    out = []
    pool = list(songs)
    while pool:
        last = out[-1]["tags"]["artist"] if out else None
        pick = next((s for s in pool if s["tags"]["artist"] != last), pool[0])
        out.append(pick)
        pool.remove(pick)
    return out


# ---- writing -------------------------------------------------------------------

def write_playlist(card, name, songs, dry):
    pdir = os.path.join(card, "Playlists")
    path = os.path.join(pdir, name + ".m3u8")
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            if MARK not in f.read(4096):
                print("  skip %-12s Playlists/%s.m3u8 is yours, not this script's" % (name, name))
                return False
    lines = ["#EXTM3U", MARK]
    for s in songs:
        t = s["tags"]
        label = " - ".join(x for x in (t["title"], t["artist"]) if x)
        lines.append("#EXTINF:%d,%s" % (int(t["length"] or -1), label))
        lines.append("../" + s["rel"])
    if dry:
        return True
    os.makedirs(pdir, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return True


def album_cover(card, rel):
    """A picture for the album a song is in: its folder's, TortOS's cached one,
    or the one in the file."""
    folder = os.path.dirname(os.path.join(card, rel))
    for name in os.listdir(folder):
        stem, ext = os.path.splitext(name)
        if ext.lower() in (".jpg", ".jpeg", ".png") and stem.lower() in ("cover", "folder", "front"):
            return os.path.join(folder, name)
    parent, album = os.path.split(folder)
    for ext in (".jpg", ".png"):
        p = os.path.join(parent, ".media", album + ext)
        if os.path.exists(p):
            return p
    try:
        import mutagen
        f = mutagen.File(os.path.join(card, rel))
        if f is not None:
            pics = getattr(f, "pictures", None)
            if pics:
                return pics[0].data
            if f.tags is not None:
                for k in f.tags.keys():
                    if k.startswith("APIC"):
                        return f.tags[k].data
                if "covr" in f.tags:
                    return bytes(f.tags["covr"][0])
    except Exception:
        pass
    return None


def write_cover(card, name, songs, color, dry):
    """The Zune way: four of its albums in a square, washed in the mood's
    color, and its name in thin lowercase across the bottom."""
    if dry:
        return
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps
        import io
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
    wash = Image.new("RGB", (size, size), color)
    img = Image.blend(img, wash, 0.55 if pics else 1.0)
    draw = ImageDraw.Draw(img)
    font, pt = None, 132
    while pt >= 48:
        try:
            font = ImageFont.truetype(FONT, pt)
        except OSError:
            font = ImageFont.load_default()
            break
        if draw.textlength(name, font=font) <= size - 48:
            break
        pt -= 8
    draw.text((24, size - 40 - pt), name, font=font, fill=(255, 255, 255))
    out = os.path.join(card, "Playlists", ".media")
    os.makedirs(out, exist_ok=True)
    img.save(os.path.join(out, name + ".jpg"), quality=90)


# ---- your own playlists --------------------------------------------------------

def fix_playlists(card, dry):
    """Point a playlist made on another computer at the card's copies of its
    songs: by file name, and the folder above it when two share a name."""
    pdir = os.path.join(card, "Playlists")
    if not os.path.isdir(pdir):
        return
    by_name = {}
    for rel, _ in songs_on(card):
        by_name.setdefault(os.path.basename(rel).lower(), []).append(rel)
    for f in sorted(os.listdir(pdir)):
        if os.path.splitext(f)[1].lower() not in (".m3u", ".m3u8"):
            continue
        path = os.path.join(pdir, f)
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            lines = fh.read().splitlines()
        if any(MARK in l for l in lines[:3]):
            continue
        changed = missing = 0
        out = []
        for line in lines:
            s = line.strip()
            if not s or s.startswith("#"):
                out.append(line)
                continue
            norm = s.replace("\\", "/")
            here = os.path.normpath(os.path.join(pdir, norm)) if not os.path.isabs(norm) else norm
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


# ---- main ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("card", help="the TORTOS drive, e.g. /Volumes/TORTOS or E:\\")
    ap.add_argument("--size", type=int, default=40, help="songs per playlist (40)")
    ap.add_argument("--moods", default=",".join(MOODS), help="which moods (all of them)")
    ap.add_argument("--mix", action="append", default=[], metavar="NAME=SEED",
                    help="a Smart DJ mix: songs that sound like SEED (artist, album or title)")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--no-covers", action="store_true")
    ap.add_argument("--fix-playlists", action="store_true",
                    help="repoint your own .m3u files at the card's copies of their songs")
    ap.add_argument("--dry-run", action="store_true", help="say what would be written")
    a = ap.parse_args()

    card = os.path.abspath(a.card)
    if not os.path.isdir(os.path.join(card, "Music")):
        sys.exit("no Music folder on %s - is that the TORTOS drive?" % card)
    moods = [m.strip() for m in a.moods.split(",") if m.strip()]
    bad = [m for m in moods if m not in MOODS]
    if bad:
        sys.exit("unknown mood %s; the moods are: %s" % (", ".join(bad), ", ".join(MOODS)))

    if a.fix_playlists:
        print("fixing your playlists")
        fix_playlists(card, a.dry_run)

    cache_dir = os.path.join(card, "Playlists", ".moods")
    cache_path = os.path.join(cache_dir, "cache.json")
    cache = load_cache(cache_path)
    todo, songs = [], []
    all_songs = list(songs_on(card))
    for rel, full in all_songs:
        c = cache["songs"].get(rel)
        if c and c.get("stamp") == stamp(full):
            songs.append(dict(c, rel=rel))
        else:
            todo.append((rel, full))
    print("%d songs on the card, %d to listen to" % (len(all_songs), len(todo)))
    if todo:
        done = 0
        with ProcessPoolExecutor(max_workers=a.jobs) as ex:
            futs = [ex.submit(_listen_job, t) for t in todo]
            for fut in as_completed(futs):
                rel, got, err = fut.result()
                done += 1
                if err:
                    print("  could not listen to %s: %s" % (rel, err))
                elif got:
                    got["stamp"] = stamp(os.path.join(card, rel))
                    cache["songs"][rel] = got
                    songs.append(dict(got, rel=rel))
                if done % 25 == 0 or done == len(todo):
                    print("  listened to %d of %d" % (done, len(todo)))
        cache["songs"] = {k: v for k, v in cache["songs"].items()
                          if os.path.exists(os.path.join(card, k))}
        if not a.dry_run:
            os.makedirs(cache_dir, exist_ok=True)
            with open(cache_path, "w") as f:
                json.dump(cache, f)
    if len(songs) < 8:
        sys.exit("only %d songs could be heard - not enough to sort into moods" % len(songs))

    keys = list(songs[0]["f"].keys())
    p = {k: percentiles(songs, k) for k in keys}
    q = {id(s): derived(s, p) for s in songs}

    # Every song's score for every mood; then each song may go in its best two,
    # so the playlists are different from one another rather than the same
    # middle-of-the-road songs seven times.
    scores = {}
    for s in songs:
        g = s["tags"].get("genre", "")
        scores[id(s)] = {m: score(q[id(s)], m) + genre_nudge(g, m) for m in MOODS}
    size = max(5, min(a.size, len(songs) // 2))
    best_two = {id(s): sorted(MOODS, key=lambda m: -scores[id(s)][m])[:2] for s in songs}

    print("writing playlists")
    for m in moods:
        forced = [s for s in songs if tagged(s["tags"].get("mood", ""), m)]
        pool = [s for s in songs if m in best_two[id(s)] and s not in forced]
        pool.sort(key=lambda s: -scores[id(s)][m])
        chosen = forced + pool[: max(0, size - len(forced))]
        if len(chosen) < size:
            # A small library: top it up from the songs that fit this mood
            # best overall, as long as they are in its top third.
            rest = sorted((s for s in songs if s not in chosen), key=lambda s: -scores[id(s)][m])
            cut = sorted(scores[id(s)][m] for s in songs)[int(len(songs) * 2 / 3)]
            chosen += [s for s in rest if scores[id(s)][m] >= cut][: size - len(chosen)]
        if len(chosen) < 3:
            print("  %-12s too few songs fit, skipped" % m)
            continue
        chosen = flow(chosen)
        if write_playlist(card, m, chosen, a.dry_run):
            if not a.no_covers:
                write_cover(card, m, chosen, MOODS[m]["color"], a.dry_run)
            print("  %-12s %d songs%s" % (m, len(chosen),
                                          " (%d by their mood tag)" % len(forced) if forced else ""))

    # Smart DJ: the songs nearest the seed's sound.
    for spec in a.mix:
        if "=" not in spec:
            sys.exit("--mix wants NAME=SEED, e.g. --mix \"sunday=Boards of Canada\"")
        name, seed = (x.strip() for x in spec.split("=", 1))
        low = seed.lower()
        seeds = [s for s in songs if low in s["tags"]["artist"].lower()
                 or low in s["tags"]["album"].lower() or low in s["tags"]["title"].lower()
                 or low in s["rel"].lower()]
        if not seeds:
            print("  %-12s nothing matches %r" % (name, seed))
            continue
        centre = {k: sum(q[id(s)][k] for s in seeds) / len(seeds) for k in q[id(seeds[0])]}

        def dist(s):
            return math.sqrt(sum((q[id(s)][k] - centre[k]) ** 2 for k in centre))

        near = sorted((s for s in songs if s not in seeds), key=dist)
        keep = seeds[: max(3, size // 4)]
        chosen = flow(keep + near[: size - len(keep)], key=dist)
        if write_playlist(card, name, chosen, a.dry_run):
            if not a.no_covers:
                hue = int(hashlib.md5(name.encode()).hexdigest()[:6], 16)
                write_cover(card, name, chosen, ((hue >> 16) & 255, (hue >> 8) & 255, hue & 255),
                            a.dry_run)
            print("  %-12s %d songs like %s" % (name, len(chosen), seed))
    print("done. On the Pixel 2: SELECT for music, then L1/R1 to the playlists pivot.")


if __name__ == "__main__":
    main()
