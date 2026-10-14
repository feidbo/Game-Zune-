"""Whole-card jobs: the Zune launcher, the library update, ejecting.

The launcher files travel with the app (dist/TortOS in the repo, bundled into
GameZune.exe), and installing follows scripts/install-to-card.sh's rules: the
stock launcher is kept once as tortos.elf.stock with the TortOS version it
came from, never replaced by a Zune one, and only put back on that version.
"""
import contextlib
import io
import os
import shutil
import subprocess
import sys

from .card import ZUNE_MARK

HERE = os.path.dirname(os.path.abspath(__file__))


def resources():
    """Where the bundled files are: beside the frozen app, or the repo."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.normpath(os.path.join(HERE, "..", ".."))


def bundled_launcher():
    for d in (os.path.join(resources(), "TortOS"), os.path.join(resources(), "dist", "TortOS")):
        if os.path.isfile(os.path.join(d, "tortos.elf")):
            return d
    return None


def bundled_version():
    d = bundled_launcher()
    try:
        with open(os.path.join(d, "ZUNE_FOR_VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except (OSError, TypeError):
        return None


def _put(src, dest):
    """Copied beside, then renamed into place: never half a file on the card."""
    shutil.copyfile(src, dest + ".new")
    os.replace(dest + ".new", dest)


def install_theme(card):
    """Put the Zune launcher on the card. Returns what was done, or raises
    RuntimeError saying why it was not."""
    src = bundled_launcher()
    if not src:
        raise RuntimeError("this copy of the app has no launcher with it")
    want, have = bundled_version(), card.version()
    if want and have != want:
        raise RuntimeError("this card has TortOS %s and the launcher is for %s. They have to "
                           "match: flash TortOS %s first." % (have, want, want))
    t = card.tortos
    notes = []
    stock = os.path.join(t, "tortos.elf.stock")
    if not os.path.exists(stock):
        with open(os.path.join(t, "tortos.elf"), "rb") as f:
            is_zune = ZUNE_MARK in f.read()
        if is_zune:
            notes.append("the launcher on the card was already a Zune one, so there is no stock "
                         "one to keep; reinstalling TortOS brings it back")
        else:
            _put(os.path.join(t, "tortos.elf"), stock)
            with open(stock + ".version", "w", encoding="utf-8") as f:
                f.write(have + "\n")
            notes.append("kept the stock launcher as tortos.elf.stock")
    os.makedirs(os.path.join(t, "fonts"), exist_ok=True)
    for n in os.listdir(os.path.join(src, "fonts")):
        _put(os.path.join(src, "fonts", n), os.path.join(t, "fonts", n))
    _put(os.path.join(src, "zune-wallpaper.jpg"), os.path.join(t, "zune-wallpaper.jpg"))
    _put(os.path.join(src, "tortos.elf"), os.path.join(t, "tortos.elf"))
    notes.append("installed the Zune launcher")
    return notes


def can_restore(card):
    return os.path.exists(os.path.join(card.tortos, "tortos.elf.stock"))


def restore_stock(card):
    t = card.tortos
    stock = os.path.join(t, "tortos.elf.stock")
    if not os.path.exists(stock):
        raise RuntimeError("there is no saved stock launcher on this card")
    try:
        with open(stock + ".version", encoding="utf-8") as f:
            was = f.read().strip()
    except OSError:
        was = card.version()
    if was != card.version():
        raise RuntimeError("the saved stock launcher is from TortOS %s and the card has %s; "
                           "reinstall TortOS %s instead" % (was, card.version(), card.version()))
    _put(stock, os.path.join(t, "tortos.elf"))
    return ["put the stock launcher back"]


# ---- the library update (scripts/zunesync.py) ------------------------------------------

def _zunesync():
    """scripts/zunesync.py: a module in the frozen app (built with it on the
    path, so its imports are bundled too), the repo's file otherwise."""
    scripts = os.path.join(resources(), "scripts")
    if os.path.isdir(scripts) and scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        import zunesync
    except ImportError:
        raise RuntimeError("zunesync.py is missing from this copy of the app")
    return zunesync


class _Lines(io.TextIOBase):
    """stdout, a line at a time, to a callback."""

    def __init__(self, out):
        self.out, self.buf = out, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.out(line)
        return len(s)


def update_library(card, out, offline=False, lastfm_key="", lastfm_user="", only=None):
    """Library index and auto playlists, as scripts/zunesync.py makes them,
    its report a line at a time to `out`."""
    zs = _zunesync()
    argv = [card.root, "--no-listen"]
    if offline:
        argv.append("--offline")
    if lastfm_key:
        argv += ["--lastfm-key", lastfm_key]
    if lastfm_user:
        argv += ["--lastfm-user", lastfm_user]
    if only:
        argv += ["--only", ",".join(only)]
    lines = _Lines(out)
    with contextlib.redirect_stdout(lines):
        try:
            zs.main(argv)
        except SystemExit as e:
            if e.code not in (None, 0):
                out(str(e.code))


def playlist_names():
    try:
        return list(_zunesync().PLAYLISTS)
    except RuntimeError:
        return []


# ---- the device's own log ------------------------------------------------------------

LOG_DIR = (".userdata", "pixel2", "logs")
LOG_KEEP = ("boot:", "scan:", "muse:", "zune:", "error", "fail", "cannot", "could not",
            "segfault", "killed", "signal", "abort")


def device_log(card, tail=40):
    """What the Pixel 2 wrote at its last two starts (tortos.log, and
    tortos.log.1 from the start before): how long each boot step took, what
    the scans found, anything that went wrong, and how each one ended."""
    out = []
    for name, what in (("tortos.log", "the last start"), ("tortos.log.1", "the start before it")):
        path = card.path(*LOG_DIR, name)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = [ln.rstrip("\n") for ln in f]
        except OSError:
            out.append("%s: no log (%s)" % (what, "/".join(LOG_DIR + (name,))))
            continue
        out.append("==== %s: %s, %d lines" % (what, name, len(lines)))
        keep = [ln for ln in lines if any(k in ln.lower() for k in LOG_KEEP)]
        out += keep[:120]
        if len(keep) > 120:
            out.append("... %d more" % (len(keep) - 120))
        out.append("---- how it ended (the last %d lines):" % min(tail, len(lines)))
        out += lines[-tail:]
        out.append("")
    return "\n".join(out)


# ---- ejecting ---------------------------------------------------------------------

def eject(card):
    """Ask the computer to let go of the card. True when it said yes."""
    root = card.root
    try:
        if sys.platform == "win32":
            drive = os.path.splitdrive(root)[0]
            ps = ("(New-Object -comObject Shell.Application).Namespace(17)"
                  ".ParseName('%s').InvokeVerb('Eject')" % drive)
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               capture_output=True, timeout=30,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        elif sys.platform == "darwin":
            r = subprocess.run(["diskutil", "eject", root], capture_output=True, timeout=30)
        else:
            r = subprocess.run(["umount", root], capture_output=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
