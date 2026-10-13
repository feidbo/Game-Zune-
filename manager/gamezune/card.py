"""The TortOS card: finding it, and what is on it.

A card is a folder (a drive on Windows) holding TortOS/ and, beside it, the
folders the Pixel 2 reads: Music/, Audiobooks/, Playlists/ and Roms/.
"""
import os
import shutil
import string
import sys

AUDIO = (".mp3", ".m4a", ".m4b", ".mp4", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wav")
IMAGES = (".jpg", ".jpeg", ".png")
ZUNE_MARK = b"zune-wallpaper.jpg"      # a string only the Zune launcher contains


def is_card(path):
    return os.path.isfile(os.path.join(path, "TortOS", "tortos.elf"))


def candidates():
    """Where a card might be mounted, on this computer."""
    if sys.platform == "win32":
        return ["%s:\\" % d for d in string.ascii_uppercase if d not in "AB"]
    roots = ["/Volumes"] if sys.platform == "darwin" else [
        "/media/" + os.environ.get("USER", ""), "/run/media/" + os.environ.get("USER", ""), "/mnt"]
    out = []
    for r in roots:
        try:
            out += [os.path.join(r, d) for d in sorted(os.listdir(r))]
        except OSError:
            pass
    return out


def find_cards():
    """Every mounted TortOS card."""
    return [p for p in candidates() if _safe_is_card(p)]


def _safe_is_card(p):
    try:
        return is_card(p)
    except OSError:          # an empty card reader, a disc drive with nothing in it
        return False


class Card:
    def __init__(self, root):
        self.root = os.path.abspath(root)

    def path(self, *rel):
        return os.path.join(self.root, *rel)

    @property
    def tortos(self):
        return self.path("TortOS")

    def version(self):
        try:
            with open(os.path.join(self.tortos, "VERSION"), encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return "unknown"

    def has_zune(self):
        """Whether the launcher on the card is the Zune one."""
        try:
            with open(os.path.join(self.tortos, "tortos.elf"), "rb") as f:
                return ZUNE_MARK in f.read()
        except OSError:
            return False

    def free_bytes(self):
        try:
            return shutil.disk_usage(self.root).free
        except OSError:
            return 0

    def rel(self, full):
        """A path on the card as the Pixel 2 writes it: from the card's top,
        with forward slashes."""
        return os.path.relpath(full, self.root).replace(os.sep, "/")

    def full(self, rel):
        return os.path.join(self.root, *rel.split("/"))


def human_size(n):
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" if unit == "bytes" else "%.1f %s") % (n, unit)
        n /= 1024.0
    return ""


# Characters FAT and exFAT refuse, and Windows besides.
_BAD = '<>:"/\\|?*'


def safe_name(s, fallback="Unknown"):
    """A file or folder name every card and computer accepts."""
    s = "".join("_" if c in _BAD or ord(c) < 32 else c for c in (s or "")).strip()
    s = s.rstrip(". ")
    if s.upper().split(".")[0] in ("CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3",
                                    "COM4", "LPT1", "LPT2", "LPT3"):
        s = "_" + s
    return s[:120] or fallback


def remove_empty_dirs(path, stop):
    """Remove `path` and its parents while they are empty, up to `stop`."""
    path = os.path.abspath(path)
    stop = os.path.abspath(stop)
    while path.startswith(stop + os.sep) and os.path.isdir(path):
        try:
            entries = [e for e in os.listdir(path) if e not in (".DS_Store", "Thumbs.db")]
            if entries:
                return
            for e in os.listdir(path):
                os.remove(os.path.join(path, e))
            os.rmdir(path)
        except OSError:
            return
        path = os.path.dirname(path)
