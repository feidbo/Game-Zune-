"""Games on the card: Roms/<system>/, with box art in Roms/<system>/.media/.

The systems are the card's own (TortOS/systems.cfg). Box art comes from the
libretro-thumbnails project - the same art TortOS fetches over Wi-Fi, which
the Pixel 2 does not have - saved under the ROM's own name, which is how the
launcher finds it.
"""
import io
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
import zipfile

from .card import safe_name
from .match import loose, similar

# name, folder, extensions - what systems.cfg says for the three Game Boys,
# for a card that has no systems.cfg to read.
DEFAULT_SYSTEMS = [
    ("Game Boy", "Game Boy", ("gb", "dmg", "zip")),
    ("Game Boy Color", "Game Boy Color", ("gbc", "cgb", "zip")),
    ("Game Boy Advance", "Game Boy Advance", ("gba", "agb", "zip")),
]
# The libretro-thumbnails repository for each, by system name.
THUMB_REPOS = {
    "Game Boy": "Nintendo_-_Game_Boy",
    "Game Boy Color": "Nintendo_-_Game_Boy_Color",
    "Game Boy Advance": "Nintendo_-_Game_Boy_Advance",
}
# Where else a game may be filed: libretro puts a cartridge that plays on
# both under one system, not always the one its file says.
SIBLINGS = {"Game Boy": ("Game Boy Color",), "Game Boy Color": ("Game Boy",),
            "Game Boy Advance": ()}
CLOSE = 0.8              # how alike a title must be for the broad search
REGIONS = ("usa", "world", "europe", "japan")   # preferred art, in order
THUMB_URL = "https://raw.githubusercontent.com/libretro-thumbnails/%s/master/Named_Boxarts/%s.png"
# Every name a system's art is under, for a game not filed under its own:
# libretro's server lists them; GitHub's API too, sixty asks an hour.
INDEX_URLS = ("https://thumbnails.libretro.com/%s/Named_Boxarts/",
              "https://api.github.com/repos/libretro-thumbnails/%s/git/trees/master?recursive=1")
UA = "GameZune/1.0 ( https://github.com/feidbo/Game-Zune- )"
ART_SIDE = 512


class System:
    def __init__(self, name, folder, exts):
        self.name, self.folder, self.exts = name, folder, tuple(e.lower() for e in exts)

    def owns(self, filename):
        return filename.lower().rsplit(".", 1)[-1] in self.exts


def systems(card):
    """The card's systems, the three Game Boys first; others only when they
    have games."""
    found = []
    try:
        with open(os.path.join(card.tortos, "systems.cfg"), encoding="utf-8") as f:
            for line in f:
                c = line.strip().split("|")
                if len(c) >= 8 and c[0] == "sys":
                    found.append(System(c[1], c[2], c[7].split(",")))
    except OSError:
        pass
    if not found:
        found = [System(*s) for s in DEFAULT_SYSTEMS]
    gb = [s for s in found if s.name in THUMB_REPOS]
    rest = [s for s in found if s.name not in THUMB_REPOS and games(card, s)]
    return gb + rest


def games(card, system):
    """ROM file names on the card for `system`, sorted."""
    d = card.path("Roms", system.folder)
    try:
        return sorted((n for n in os.listdir(d) if not n.startswith(".") and system.owns(n)
                       and os.path.isfile(os.path.join(d, n))), key=str.lower)
    except OSError:
        return []


def art_path(card, system, rom):
    return card.path("Roms", system.folder, ".media", os.path.splitext(rom)[0] + ".png")


def has_art(card, system, rom):
    return os.path.exists(art_path(card, system, rom))


def _inner_ext(path):
    """The extension of the game inside a .zip, to tell which system it is."""
    try:
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                ext = n.lower().rsplit(".", 1)[-1]
                if ext in ("gb", "dmg", "gbc", "cgb", "gba", "agb"):
                    return ext
    except (OSError, zipfile.BadZipFile):
        pass
    return None


def system_for(syss, path):
    """Which system a ROM file is for, or None."""
    name = os.path.basename(path)
    ext = name.lower().rsplit(".", 1)[-1]
    if ext == "zip":
        ext = _inner_ext(path)
        if not ext:
            return None
    for s in syss:
        if ext in s.exts:
            return s
    return None


def import_roms(card, paths, progress=None):
    """Copy ROMs onto the card, each to its system. (added, skipped, failed),
    lists of (source, where or why)."""
    syss = systems(card)
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, names in os.walk(p):
                files += [os.path.join(root, n) for n in sorted(names)]
        else:
            files.append(p)
    added, skipped, failed = [], [], []
    for i, src in enumerate(files):
        if progress:
            progress(i, len(files), os.path.basename(src))
        s = system_for(syss, src)
        if not s:
            skipped.append((src, "not a Game Boy game"))
            continue
        dest = card.path("Roms", s.folder, safe_name(os.path.basename(src)))
        try:
            if os.path.exists(dest) and os.path.getsize(dest) == os.path.getsize(src):
                skipped.append((src, "already on the card"))
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(src, dest + ".part")
            os.replace(dest + ".part", dest)
            added.append((src, "%s/%s" % (s.name, os.path.basename(dest))))
        except OSError as e:
            failed.append((src, str(e)))
    if progress:
        progress(len(files), len(files), "")
    return added, skipped, failed


def delete_games(card, system, roms):
    for rom in roms:
        for p in (card.path("Roms", system.folder, rom), art_path(card, system, rom)):
            try:
                os.remove(p)
            except OSError:
                pass


# ---- box art ------------------------------------------------------------------------

def thumb_names(rom):
    """The names libretro-thumbnails might file a game under: its own, with
    the characters it replaces replaced, then without [bracketed] tags."""
    stem = os.path.splitext(rom)[0]
    out = []
    for s in (stem, " ".join(p for p in stem.split(" ") if not p.startswith("["))):
        name = "".join("_" if c in '&*/:`<>?\\|"' else c for c in s).strip()
        if name and name not in out:
            out.append(name)
    return out


def _tags(name):
    """A No-Intro name's title and its (tags): "Tetris (World) (Rev 1)" is
    ("tetris", {"world", "rev 1"})."""
    stem = os.path.splitext(name)[0]
    cut = min([i for i in (stem.find(" ("), stem.find(" [")) if i >= 0] or [len(stem)])
    tags = set()
    for part in re.findall(r"[(\[]([^)\]]*)[)\]]", stem[cut:]):
        tags |= {t.strip().lower() for t in part.split(",") if t.strip()}
    return " ".join(stem[:cut].lower().split()), tags


def best_match(rom, names):
    """The art name in `names` that is this game, or None: its own name, or
    the same title with more tags ("(Rev 1)"), else the same title sharing
    the most of its tags - a region over none. Never another title."""
    stem = thumb_names(rom)[0]
    if stem in names:
        return stem
    title, tags = _tags(stem)
    best, score = None, -1
    for n in names:
        t, ntags = _tags(n)
        if t != title:
            continue
        sc = 100 if n.startswith(stem + " ") else 10 * len(tags & ntags) - len(ntags - tags)
        if sc > score:
            best, score = n, sc
    return best


def close_match(rom, names):
    """The broader search, for a game best_match did not find: the name in
    `names` whose title is most like this game's - "Pokemon Red.gb" finds
    "Pokemon - Red Version (USA, Europe)", "Legend of Zelda, The - Link's
    Awakening DX" finds "The Legend of Zelda - Link's Awakening DX", "Pokemon
    Yellow" "Pokemon - Yellow Version - Special Pikachu Edition" - with
    the USA's art, then the world's, Europe's, Japan's, when several are."""
    title, tags = _tags(thumb_names(rom)[0])
    want = loose(title, music=False)
    best, key = None, None
    for n in names:
        t, ntags = _tags(n)
        # The whole title, and without its last subtitles: "Pokemon Yellow"
        # is "Pokemon - Yellow Version - Special Pikachu Edition".
        parts = t.split(" - ")
        sc = max(similar(want, loose(" - ".join(parts[:k]), music=False))
                 for k in range(len(parts), 0, -1))
        if sc < CLOSE:
            continue
        region = min([REGIONS.index(r) for r in ntags if r in REGIONS] or [len(REGIONS)])
        k = (round(sc, 3), len(tags & ntags), -region, -len(ntags))
        if key is None or k > key:
            best, key = n, k
    return best


_index_cache = {}


def art_index(system, fetch=None):
    """Every name `system`'s box art is filed under, or [] when no list could
    be had. Asked once a run."""
    fetch = fetch or _fetch
    if system.name in _index_cache:
        return _index_cache[system.name]
    names = []
    repo = THUMB_REPOS.get(system.name, "")
    for url in (INDEX_URLS[0] % urllib.parse.quote(repo.replace("_-_", " - ").replace("_", " ")),
                INDEX_URLS[1] % repo):
        data = fetch(url)
        if not data:
            continue
        text = data.decode("utf-8", "replace")
        if text.lstrip().startswith("{"):
            try:
                tree = json.loads(text).get("tree", [])
            except ValueError:
                tree = []
            names = [os.path.splitext(t["path"].split("/", 1)[1])[0] for t in tree
                     if t.get("path", "").startswith("Named_Boxarts/") and t["path"].endswith(".png")]
        else:
            names = [os.path.splitext(urllib.parse.unquote(h))[0]
                     for h in re.findall(r'href="([^"/?]+\.png)"', text)]
        if names:
            break
    _index_cache[system.name] = names
    return names


def _fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def fetch_art(card, system, rom, fetch=_fetch):
    """Download a game's box art onto the card. How it was found - "exact",
    "close" or "other system" (a close match among a sibling's art, Game Boy
    for Game Boy Color and the other way) - or None when it was not."""
    if system.name not in THUMB_REPOS:
        return None
    tried = set()

    def get(sysname, name):
        if not name or (sysname, name) in tried:
            return False
        tried.add((sysname, name))
        data = fetch(THUMB_URL % (THUMB_REPOS[sysname], urllib.parse.quote(name)))
        if not (data and data[:8] == b"\x89PNG\r\n\x1a\n"):
            return False
        out = art_path(card, system, rom)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out + ".part", "wb") as f:
            f.write(_shrink(data))
        os.replace(out + ".part", out)
        return True

    # Strict: under its own name, then the same title with other tags.
    for name in thumb_names(rom):
        if get(system.name, name):
            return "exact"
    names = art_index(system, fetch)
    if get(system.name, best_match(rom, names)):
        return "exact"
    # Broader: the most alike title, then the same among a sibling's art.
    if get(system.name, close_match(rom, names)):
        return "close"
    for other in SIBLINGS.get(system.name, ()):
        sib = System(other, other, ())
        if get(other, best_match(rom, art_index(sib, fetch)) or close_match(rom, art_index(sib, fetch))):
            return "other system"
    return None


def _shrink(png):
    """No bigger than the launcher draws it: smaller on the card, faster to load."""
    try:
        from PIL import Image
    except ImportError:
        return png
    try:
        im = Image.open(io.BytesIO(png))
        if max(im.size) <= ART_SIDE:
            return png
        im.thumbnail((ART_SIDE, ART_SIDE))
        b = io.BytesIO()
        im.save(b, "PNG", optimize=True)
        return b.getvalue()
    except Exception:
        return png
