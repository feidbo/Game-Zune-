"""Playlists on the card: Playlists/<name>.m3u8, one song a line.

Three kinds, told apart by their first lines:
  liked songs   kept by the Pixel 2 (Y on Now Playing). It IS the record of
                what is liked, so editing it here likes and unlikes.
  auto          one of the nine scripts/zunesync.py writes; "update" rewrites
                it, so it is copied before it is changed.
  yours         everything else.

Lines are read the way the Pixel 2 reads them (src/muselib.c): beside the
playlist, from the card's top, or from the Music or Audiobooks folder in a
path from another computer. A line that names nothing on the card is kept as
it is when the playlist is saved, so a song that is off the card for now
comes back with it.
"""
import os
import urllib.parse

from .card import AUDIO, safe_name

LIKED = "liked songs"
AUTO_MARKS = ("# made by Game Zune zunesync", "# made by Game Zune moodlists")
LIKED_HEADER = ("# kept by Game Zune on the Pixel 2: the songs you like, in the order you"
                " liked them. Like or unlike a song there, or add or remove lines here.")


class Playlist:
    def __init__(self, card, path):
        self.card = card
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.songs = []          # card paths, in order
        self.kept = []           # lines that name nothing on the card now
        self.kind = "yours"
        self.load()

    @property
    def editable(self):
        return self.kind != "auto"

    def load(self):
        self.songs, self.kept = [], []
        try:
            with open(self.path, "rb") as f:
                raw = f.read()
        except OSError:
            return
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        head = text[:4096]
        if self.name.lower() == LIKED:
            self.kind = "liked"
        elif any(m in head for m in AUTO_MARKS):
            self.kind = "auto"
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rel = resolve(self.card, line)
            if rel:
                if rel not in self.songs or self.kind != "liked":
                    self.songs.append(rel)
            else:
                self.kept.append(line)

    def save(self, titles=None):
        """Written whole or not at all, UTF-8, paths beside the playlist.
        `titles`: card path -> (seconds, "title - artist"), for #EXTINF."""
        lines = ["#EXTM3U"]
        if self.kind == "liked":
            lines.append(LIKED_HEADER)
        for rel in self.songs:
            if titles and rel in titles:
                secs, label = titles[rel]
                lines.append("#EXTINF:%d,%s" % (secs or -1, " ".join(label.split())))
            lines.append("../" + rel)
        lines += self.kept
        write_atomic(self.path, "\n".join(lines) + "\n")


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _squash(parts):
    out = []
    for p in parts:
        if p in ("", "."):
            continue
        if p == "..":
            if not out:
                return None
            out.pop()
        else:
            out.append(p)
    return "/".join(out) if out else None


def _is_song(card, rel):
    return bool(rel) and rel.lower().endswith(AUDIO) and os.path.isfile(card.full(rel))


def resolve(card, line):
    """The card path a playlist line names, or None."""
    s = line.strip().lstrip("﻿")
    if s.lower().startswith("file://"):
        s = urllib.parse.unquote(urllib.parse.urlparse(s).path)
    s = s.replace("\\", "/")
    if not s.startswith("/") and ":" not in s:
        for base in (["Playlists"], []):
            rel = _squash(base + s.split("/"))
            if _is_song(card, rel):
                return rel
    parts = s.split("/")
    for folder in ("Music", "Audiobooks"):
        for i, p in enumerate(parts):
            if p.lower() == folder.lower():
                rel = _squash([folder] + parts[i + 1:])
                if _is_song(card, rel):
                    return rel
    return None


def all_playlists(card):
    """Every playlist on the card, liked songs first, then by name."""
    d = card.path("Playlists")
    try:
        names = [n for n in os.listdir(d)
                 if os.path.splitext(n)[1].lower() in (".m3u", ".m3u8") and not n.startswith(".")]
    except OSError:
        names = []
    out = [Playlist(card, os.path.join(d, n)) for n in names]
    out.sort(key=lambda p: (p.kind != "liked", p.name.lower()))
    return out


def liked(card):
    """liked songs, made empty if the Pixel 2 has not made it yet."""
    p = Playlist(card, card.path("Playlists", LIKED + ".m3u8"))
    p.kind = "liked"
    return p


def _cover(card, name):
    for ext in (".jpg", ".png"):
        p = card.path("Playlists", ".media", name + ext)
        if os.path.exists(p):
            return p
    return None


def create(card, name):
    """A new, empty playlist of yours. Raises ValueError for a name in use."""
    name = safe_name(name, "")
    if not name:
        raise ValueError("a playlist needs a name")
    path = card.path("Playlists", name + ".m3u8")
    if os.path.exists(path) or name.lower() == LIKED:
        raise ValueError("there is already a playlist called %s" % name)
    p = Playlist(card, path)
    p.save()
    return p


def rename(card, pl, new):
    new = safe_name(new, "")
    if not new or new.lower() == LIKED or pl.kind != "yours":
        raise ValueError("that playlist cannot be renamed to that")
    path = card.path("Playlists", new + os.path.splitext(pl.path)[1])
    if os.path.exists(path):
        raise ValueError("there is already a playlist called %s" % new)
    os.replace(pl.path, path)
    cov = _cover(card, pl.name)
    if cov:
        os.replace(cov, card.path("Playlists", ".media", new + os.path.splitext(cov)[1]))
    return Playlist(card, path)


def copy(card, pl, new):
    """An editable copy of an auto playlist."""
    p = create(card, new)
    p.songs = list(pl.songs)
    p.save()
    return p


def delete(card, pl):
    os.remove(pl.path)
    cov = _cover(card, pl.name)
    if cov:
        os.remove(cov)


def forget(card, rels):
    """Songs that have left the card, taken off your playlists and liked songs
    (the auto ones are rebuilt by update)."""
    rels = set(rels)
    for pl in all_playlists(card):
        if pl.editable and any(r in rels for r in pl.songs):
            pl.songs = [r for r in pl.songs if r not in rels]
            pl.save()
