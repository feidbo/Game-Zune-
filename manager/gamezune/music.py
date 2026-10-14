"""The music on the card: reading it, adding to it, taking from it.

Songs go where the Pixel 2 looks for them and the way its library groups them:
Music/<artist>/<album>/<NN - title>.<ext>, the artist being the album's
artist where the tags name one, so a compilation stays one album. Each album
gets its cover beside it as cover.jpg when there is one to be had.
"""
import os
import re
import shutil

from .card import AUDIO, IMAGES, remove_empty_dirs, safe_name

try:
    import mutagen
except ImportError:          # the app still lists and copies without it
    mutagen = None


class Track:
    __slots__ = ("rel", "title", "artist", "album", "num", "secs", "genre", "year")

    def __init__(self, rel, title="", artist="", album="", num=0, secs=0, genre="", year=0):
        self.rel, self.title, self.artist, self.album = rel, title, artist, album
        self.num, self.secs, self.genre, self.year = num, secs, genre, year

    def label(self):
        return "%s - %s" % (self.title, self.artist) if self.artist else self.title


def _first(tags, *keys):
    for k in keys:
        v = tags.get(k) if tags else None
        if v:
            return str(v[0] if isinstance(v, list) else v).strip()
    return ""


def _number(s):
    m = re.match(r"\s*(\d+)", s or "")
    return int(m.group(1)) if m else 0


def read_tags(path):
    """title, artist, album artist, album, track, disc, seconds, genre, year -
    whatever the file says, "" and 0 where it says nothing."""
    out = dict(title="", artist="", albumartist="", album="", num=0, disc=0, secs=0, genre="", year=0)
    if mutagen is None:
        return out
    try:
        f = mutagen.File(path, easy=True)
    except Exception:
        f = None
    if f is None:
        return out
    t = f.tags or {}
    out.update(title=_first(t, "title"), artist=_first(t, "artist"),
               albumartist=_first(t, "albumartist", "album artist"),
               album=_first(t, "album"), num=_number(_first(t, "tracknumber")),
               disc=_number(_first(t, "discnumber")), genre=_first(t, "genre"),
               year=_number(_first(t, "date", "year")))
    if getattr(f, "info", None) and getattr(f.info, "length", 0):
        out["secs"] = int(f.info.length + 0.5)
    return out


def _name_from_file(fn):
    stem = os.path.splitext(fn)[0]
    m = re.match(r"^\s*(\d{1,3})\s*[-._ ]\s*(.+)$", stem)
    return (int(m.group(1)), m.group(2).strip()) if m else (0, stem)


def _index(card):
    """Music/.zune/library.tsv, when scripts/zunesync.py has written one: the
    real titles, without opening every file."""
    out = {}
    try:
        with open(card.path("Music", ".zune", "library.tsv"), encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                c = line.rstrip("\r\n").split("\t")
                if len(c) >= 8:
                    out[c[0]] = c
    except OSError:
        pass
    return out


def scan(card, tags=True, progress=None):
    """Every song in Music/, by artist, album and track. With `tags`, files
    the library index does not know are opened for theirs."""
    idx = _index(card)
    out = []
    music = card.path("Music")
    files = []
    for root, dirs, names in os.walk(music):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        files += [os.path.join(root, n) for n in sorted(names)
                  if n.lower().endswith(AUDIO) and not n.startswith(".")]
    for i, full in enumerate(files):
        rel = card.rel(full)
        parts = rel.split("/")
        num, title = _name_from_file(parts[-1])
        artist = parts[1] if len(parts) >= 4 else ""
        album = parts[2] if len(parts) >= 4 else (parts[1] if len(parts) == 3 else "")
        t = Track(rel, title, artist, album, num)
        c = idx.get(rel)
        if c:
            t.title = c[1] or t.title
            t.artist = c[2] or t.artist
            t.genre = c[4]
            t.year = _number(c[5])
            t.secs = _number(c[6])
            t.num = _number(c[7]) or t.num
        elif tags:
            g = read_tags(full)
            t.title = g["title"] or t.title
            t.artist = g["artist"] or t.artist
            t.secs, t.genre, t.year = g["secs"], g["genre"], g["year"]
            t.num = g["num"] or t.num
        out.append(t)
        if progress and i % 50 == 0:
            progress(i, len(files))
    return out


def group(tracks):
    """{artist: {album: [tracks in order]}}, by the folders the songs are in."""
    lib = {}
    for t in tracks:
        parts = t.rel.split("/")
        artist = parts[1] if len(parts) >= 4 else "(singles)"
        album = parts[2] if len(parts) >= 4 else (parts[1] if len(parts) == 3 else "(singles)")
        lib.setdefault(artist, {}).setdefault(album, []).append(t)
    for albums in lib.values():
        for songs in albums.values():
            songs.sort(key=lambda t: (t.num or 999, t.title.lower()))
    return lib


# ---- adding -----------------------------------------------------------------------

def audio_files(paths):
    """The songs in `paths`: files, and every song in a folder, recursively."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, names in os.walk(p):
                dirs.sort()
                out += [os.path.join(root, n) for n in sorted(names)
                        if n.lower().endswith(AUDIO) and not n.startswith(".")]
        elif p.lower().endswith(AUDIO):
            out.append(p)
    return out


def destination(card, src, tags):
    """Where a song goes on the card, from its tags (or its folders, without)."""
    parent = os.path.basename(os.path.dirname(os.path.abspath(src)))
    artist = tags["albumartist"] or tags["artist"] or "Unknown Artist"
    album = tags["album"] or parent or "Unknown Album"
    num, title = _name_from_file(os.path.basename(src))
    title = tags["title"] or title
    num = tags["num"] or num
    ext = os.path.splitext(src)[1].lower()
    name = ("%02d - %s" % (num, title)) if num else title
    if tags["disc"] > 1:
        name = "%d-%s" % (tags["disc"], name)
    return card.path("Music", safe_name(artist), safe_name(album), safe_name(name) + ext)


def _same_file(a, b):
    try:
        return os.path.getsize(a) == os.path.getsize(b)
    except OSError:
        return False


def _cover_for(src_dir, first_song):
    """An album's picture: a cover/folder/front image beside the songs, or
    the one inside the first song. (path or bytes, extension) or None."""
    try:
        for n in sorted(os.listdir(src_dir)):
            stem, ext = os.path.splitext(n)
            if ext.lower() in IMAGES and stem.lower() in ("cover", "folder", "front", "albumart"):
                return os.path.join(src_dir, n), ext.lower().replace(".jpeg", ".jpg")
    except OSError:
        pass
    if mutagen is None:
        return None
    try:
        f = mutagen.File(first_song)
    except Exception:
        return None
    if f is None:
        return None
    pics = getattr(f, "pictures", None)
    if pics:
        return pics[0].data, ".png" if pics[0].mime == "image/png" else ".jpg"
    tags = f.tags or {}
    for k in list(getattr(tags, "keys", lambda: [])()):
        if str(k).startswith("APIC"):
            return tags[k].data, ".png" if tags[k].mime == "image/png" else ".jpg"
    if "covr" in tags and tags["covr"]:
        c = tags["covr"][0]
        return bytes(c), ".png" if getattr(c, "imageformat", 0) == 14 else ".jpg"
    return None


def _has_cover(folder):
    """Whether the Pixel 2 has a picture for this folder: one called cover or
    folder, or the only picture there (src/muselib.c, ml_folder_image)."""
    try:
        pics = [n for n in os.listdir(folder)
                if not n.startswith(".") and os.path.splitext(n)[1].lower() in IMAGES]
    except OSError:
        return False
    return len(pics) == 1 or any(os.path.splitext(n)[0].lower() in ("cover", "folder") for n in pics)


def has_cover(card, rel):
    return _has_cover(card.full(rel))


def _write_cover(folder, data, ext):
    out = os.path.join(folder, "cover" + ext)
    if isinstance(data, str):
        shutil.copyfile(data, out + ".part")
    else:
        with open(out + ".part", "wb") as fh:
            fh.write(data)
    os.replace(out + ".part", out)


def import_songs(card, paths, progress=None, cancelled=lambda: False):
    """Copy the songs in `paths` onto the card, organized. Returns
    (added, skipped, failed) as lists of (source, card path or reason)."""
    added, skipped, failed = [], [], []
    songs = audio_files(paths)
    covers_done = set()
    for i, src in enumerate(songs):
        if cancelled():
            break
        if progress:
            progress(i, len(songs), os.path.basename(src))
        tags = read_tags(src)
        dest = destination(card, src, tags)
        try:
            if os.path.exists(dest) and _same_file(src, dest):
                skipped.append((src, "already on the card"))
                continue
            stem, ext = os.path.splitext(dest)
            k = 2
            while os.path.exists(dest):
                dest = "%s (%d)%s" % (stem, k, ext)
                k += 1
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(src, dest + ".part")
            os.replace(dest + ".part", dest)
            added.append((src, card.rel(dest)))
        except OSError as e:
            failed.append((src, str(e)))
            continue
        folder = os.path.dirname(dest)
        if folder not in covers_done and not _has_cover(folder):
            covers_done.add(folder)
            cover = _cover_for(os.path.dirname(src), src)
            if cover:
                try:
                    _write_cover(folder, *cover)
                except OSError:
                    pass
    if progress:
        progress(len(songs), len(songs), "")
    return added, skipped, failed


# ---- covers from the internet ----------------------------------------------------------

def albums_without_covers(card, tracks):
    """[(folder, artist, album, [song titles])] for each album folder the
    Pixel 2 has no picture for."""
    folders = {}
    for t in tracks:
        if not t.rel.startswith("Music/"):
            continue
        folders.setdefault(t.rel.rsplit("/", 1)[0], []).append(t)
    out = []
    for rel, ts in sorted(folders.items()):
        parts = rel.split("/")
        # Songs loose in Music/ are no album: one picture would be all of theirs.
        if len(parts) < 2 or _has_cover(card.full(rel)):
            continue
        # Music/<artist>/<album>/, or Music/<artist>/ with the songs in it:
        # then there is no album name, and the songs find the cover.
        artist = parts[1]
        album = parts[2] if len(parts) >= 3 else ""
        out.append((rel, artist, album, [t.title for t in sorted(ts, key=lambda t: t.num) if t.title]))
    return out


def get_covers(card, tracks, finder=None, progress=None, cancelled=lambda: False):
    """A cover for every album folder without one: from its own songs first,
    then looked up (gamezune/albumart.py). Returns (got, missing): got a
    list of (folder, how), how being "from its files", "exact", "close" or
    "by song"; missing the folders nothing was found for."""
    from .albumart import Finder
    finder = finder or Finder()
    todo = albums_without_covers(card, tracks)
    got, missing = [], []
    for i, (rel, artist, album, titles) in enumerate(todo):
        if cancelled():
            break
        if progress:
            progress(i, len(todo), "%s - %s" % (album or rel.rsplit("/", 1)[-1], artist))
        folder = card.full(rel)
        songs = sorted(n for n in os.listdir(folder) if n.lower().endswith(AUDIO))
        local = _cover_for(folder, os.path.join(folder, songs[0])) if songs else None
        try:
            if local:
                _write_cover(folder, *local)
                got.append((rel, "from its files"))
                continue
            url, how = finder.find(artist, album, titles)
            data = finder.picture(url)
            if data:
                _write_cover(folder, data, ".jpg")
                got.append((rel, how))
            else:
                missing.append(rel)
        except OSError:
            missing.append(rel)
    if progress:
        progress(len(todo), len(todo), "")
    return got, missing


# ---- taking away --------------------------------------------------------------------

def delete_songs(card, rels):
    """Remove songs from the card, and their album and artist folders when
    nothing is left in them but pictures."""
    gone = []
    folders = set()
    for rel in rels:
        full = card.full(rel)
        try:
            os.remove(full)
            gone.append(rel)
            folders.add(os.path.dirname(full))
        except OSError:
            pass
    for folder in folders:
        try:
            left = os.listdir(folder)
        except OSError:
            continue
        if not any(n.lower().endswith(AUDIO) for n in left):
            for n in left:
                if n.lower().endswith(IMAGES) or n in (".DS_Store", "Thumbs.db"):
                    try:
                        os.remove(os.path.join(folder, n))
                    except OSError:
                        pass
        remove_empty_dirs(folder, card.path("Music"))
    return gone
