"""Game Zune for the computer: the card's music, playlists and games.

A tkinter window in the Zune software's manner - black, lowercase, magenta -
over the modules beside it, which do the work. Anything slow (copying,
reading tags, the library update) runs on a worker thread and reports back
through a queue the window reads ten times a second.
"""
import json
import os
import queue
import sys
import threading
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import device, games, music, playlists
from .card import Card, find_cards, human_size, is_card

BG, PANEL, FG, DIM, FAINT, ACCENT = "#0d0d0f", "#1a1a1e", "#f2f2f2", "#9a9aa2", "#5a5a62", "#ec008c"
FONT = "Segoe UI" if sys.platform == "win32" else ("Helvetica Neue" if sys.platform == "darwin" else "DejaVu Sans")


def settings_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    return os.path.join(base, "GameZune", "settings.json")


def load_settings():
    try:
        with open(settings_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(s):
    try:
        os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(s, f, indent=1)
    except OSError:
        pass


def mmss(secs):
    return "%d:%02d" % (secs // 60, secs % 60) if secs else ""


class App(tk.Tk):
    PAGES = ("music", "playlists", "games", "device")

    def __init__(self, start=None):
        super().__init__()
        self.title("Game Zune")
        self.geometry("1180x760")
        self.minsize(900, 600)
        self.configure(bg=BG)
        for ico in (os.path.join(device.resources(), "gamezune.ico"),
                    os.path.join(device.resources(), "manager", "gamezune.ico")):
            if sys.platform == "win32" and os.path.exists(ico):
                try:
                    self.iconbitmap(ico)
                except tk.TclError:
                    pass
                break
        self.settings = load_settings()
        self.card = None
        self.tracks = []
        self.by_rel = {}
        self.events = queue.Queue()
        self.busy = False
        self._style()
        self._chrome()
        self.pages = {"music": MusicPage(self), "playlists": PlaylistsPage(self),
                      "games": GamesPage(self), "device": DevicePage(self)}
        self.show("music")
        self.after(100, self._pump)
        self.refresh_cards(start)

    # ---- look -------------------------------------------------------------------

    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, fieldbackground=PANEL, bordercolor=PANEL,
                    font=(FONT, 10))
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Dim.TLabel", foreground=DIM)
        s.configure("Head.TLabel", font=(FONT, 15), foreground=FG)
        s.configure("TButton", background=PANEL, foreground=FG, borderwidth=0, padding=(12, 6),
                    font=(FONT, 10))
        s.map("TButton", background=[("active", "#2a2a30"), ("disabled", BG)],
              foreground=[("disabled", FAINT)])
        s.configure("Accent.TButton", background=ACCENT, foreground="white")
        s.map("Accent.TButton", background=[("active", "#ff2aa6"), ("disabled", PANEL)])
        s.configure("TCheckbutton", background=BG, foreground=FG)
        s.map("TCheckbutton", background=[("active", BG)])
        s.configure("TEntry", fieldbackground=PANEL, foreground=FG, insertcolor=FG)
        s.configure("TCombobox", fieldbackground=PANEL, foreground=FG, background=PANEL,
                    arrowcolor=FG)
        s.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)])
        s.configure("Treeview", background=BG, fieldbackground=BG, foreground=FG, rowheight=26,
                    borderwidth=0, font=(FONT, 10))
        s.map("Treeview", background=[("selected", "#3a1030")], foreground=[("selected", "white")])
        s.configure("Treeview.Heading", background=BG, foreground=DIM, borderwidth=0,
                    font=(FONT, 9))
        s.map("Treeview.Heading", background=[("active", BG)])
        s.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=PANEL, borderwidth=0)
        s.configure("Vertical.TScrollbar", background=PANEL, troughcolor=BG, borderwidth=0,
                    arrowcolor=DIM)

    def _chrome(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=24, pady=(14, 0))
        tk.Label(top, text="game zune", bg=BG, fg=DIM, font=(FONT, 11)).pack(side="left")
        right = tk.Frame(top, bg=BG)
        right.pack(side="right")
        self.card_box = ttk.Combobox(right, state="readonly", width=34)
        self.card_box.pack(side="left", padx=(0, 6))
        self.card_box.bind("<<ComboboxSelected>>", lambda e: self.open_card(self.card_box.get()))
        ttk.Button(right, text="refresh", command=self.refresh_cards).pack(side="left", padx=2)
        ttk.Button(right, text="choose folder...", command=self.choose_card).pack(side="left", padx=2)

        piv = tk.Frame(self, bg=BG)
        piv.pack(fill="x", padx=20, pady=(2, 6))
        self.pivots = {}
        for name in self.PAGES:
            l = tk.Label(piv, text=name, bg=BG, fg=FAINT, font=(FONT, 30), cursor="hand2")
            l.pack(side="left", padx=(4, 26))
            l.bind("<Button-1>", lambda e, n=name: self.show(n))
            self.pivots[name] = l

        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True, padx=24)

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", padx=24, pady=(4, 10))
        self.status = tk.Label(foot, text="", bg=BG, fg=DIM, font=(FONT, 9), anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(foot, length=220, mode="determinate")
        self.progress.pack(side="right")

    def show(self, name):
        for n, l in self.pivots.items():
            l.configure(fg=FG if n == name else FAINT)
        for p in getattr(self, "pages", {}).values():
            p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.pages[name].shown()
        self.current = name

    # ---- the card ------------------------------------------------------------------

    def refresh_cards(self, prefer=None):
        found = find_cards()
        last = self.settings.get("card")
        for p in (prefer, last):
            if p and is_card(p) and p not in found:
                found.insert(0, p)
        self.card_box["values"] = found or ["no card found"]
        pick = prefer if prefer in found else (self.card.root if self.card and self.card.root in found
                                               else (last if last in found else (found[0] if found else None)))
        if pick:
            self.card_box.set(pick)
            self.open_card(pick)
        else:
            self.card_box.set("no card found - put it in, then refresh")
            self.card = None
            self.set_status("no card: put the Pixel 2's SD card in this computer and press refresh, "
                            "or choose its folder")
            for p in self.pages.values():
                p.card_changed()

    def choose_card(self):
        d = filedialog.askdirectory(title="The TORTOS card (the folder with TortOS in it)")
        if not d:
            return
        if not is_card(d):
            messagebox.showerror("Game Zune", "There is no TortOS/tortos.elf in %s.\n\nChoose the "
                                 "card itself - the drive that has the TortOS folder." % d)
            return
        self.refresh_cards(d)

    def open_card(self, path):
        if not is_card(path):
            return
        self.card = Card(path)
        self.settings["card"] = self.card.root
        save_settings(self.settings)
        self.reload_music()
        for p in self.pages.values():
            p.card_changed()

    def reload_music(self, then=None):
        if not self.card:
            return
        card = self.card

        def work(report):
            return music.scan(card, progress=lambda i, n: report(i, n, "reading the music"))

        def done(tracks):
            self.tracks = tracks
            self.by_rel = {t.rel: t for t in tracks}
            self.card_status()
            self.pages["music"].fill()
            self.pages["playlists"].library_changed()
            if then:
                then()
        self.run(work, done, "reading the music")

    def card_status(self):
        if not self.card:
            return
        albums = {t.rel.rsplit("/", 1)[0] for t in self.tracks}
        self.set_status("%s   -   %d songs, %d albums   -   %s free" % (
            self.card.root, len(self.tracks), len(albums), human_size(self.card.free_bytes())))

    def titles(self):
        """card path -> (seconds, "title - artist"), for playlist files."""
        return {t.rel: (t.secs, t.label()) for t in self.tracks}

    # ---- work off the window's thread ------------------------------------------------

    def set_status(self, text):
        self.status.configure(text=text)

    def run(self, work, done=None, what="working"):
        """`work(report)` on a thread; `done(result)` back on this one."""
        if self.busy:
            messagebox.showinfo("Game Zune", "Still %s - one thing at a time." % self.busy)
            return
        self.busy = what
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.set_status(what + "...")

        def report(i, n, text=""):
            self.events.put(("progress", (i, n, text)))

        def body():
            try:
                r = work(report)
                self.events.put(("done", (done, r)))
            except Exception as e:
                self.events.put(("error", (what, e, traceback.format_exc())))
        threading.Thread(target=body, daemon=True).start()

    def _pump(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "progress":
                    i, n, text = data
                    if n:
                        self.progress.stop()
                        self.progress.configure(mode="determinate", maximum=n, value=i)
                    if text:
                        self.set_status("%s  (%d of %d)" % (text, min(i + 1, n), n) if n else text)
                elif kind == "log":
                    self.pages["device"].log(data)
                elif kind in ("done", "error"):
                    self.busy = False
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    if kind == "done":
                        fn, r = data
                        self.card_status()
                        if fn:
                            fn(r)
                    else:
                        what, e, tb = data
                        self.card_status()
                        sys.stderr.write(tb)
                        messagebox.showerror("Game Zune", "%s failed:\n\n%s" % (what, e))
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def need_card(self):
        if not self.card:
            messagebox.showinfo("Game Zune", "Put the card in first (or choose its folder).")
            return False
        return True


def tree(parent, columns, widths, stretch=None, selectmode="extended"):
    """A dark list with a scrollbar: (frame, treeview). Column headings only
    where there is something to say in them."""
    f = tk.Frame(parent, bg=BG)
    t = ttk.Treeview(f, columns=[c for c, _ in columns], selectmode=selectmode,
                     show="headings" if any(h for _, h in columns) else "")
    for (c, head), w in zip(columns, widths):
        t.heading(c, text=head, anchor="w")
        t.column(c, width=w, anchor="w", stretch=(c == stretch))
    sb = ttk.Scrollbar(f, orient="vertical", command=t.yview)
    t.configure(yscrollcommand=sb.set)
    t.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return f, t


def header(parent, text):
    return ttk.Label(parent, text=text, style="Head.TLabel")


def summary(what, added, skipped, failed):
    lines = ["%s: %d added" % (what, len(added))]
    if skipped:
        lines.append("%d skipped (%s)" % (len(skipped), skipped[0][1]))
    if failed:
        lines.append("%d failed:" % len(failed))
        lines += ["  %s: %s" % (os.path.basename(s), why) for s, why in failed[:8]]
    return "\n".join(lines)


class Page(tk.Frame):
    def __init__(self, app):
        super().__init__(app.body, bg=BG)
        self.app = app

    def shown(self):
        pass

    def card_changed(self):
        pass


# ---- music ------------------------------------------------------------------------

class MusicPage(Page):
    def __init__(self, app):
        super().__init__(app)
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="add songs...", style="Accent.TButton", command=self.add_files).pack(side="left")
        ttk.Button(bar, text="add a folder...", command=self.add_folder).pack(side="left", padx=6)
        ttk.Button(bar, text="delete", command=self.delete).pack(side="left")
        ttk.Button(bar, text="add to playlist...", command=self.to_playlist).pack(side="left", padx=6)
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *a: self.fill_songs())
        e = ttk.Entry(bar, textvariable=self.search, width=30)
        e.pack(side="right")
        ttk.Label(bar, text="search", style="Dim.TLabel").pack(side="right", padx=6)

        cols = tk.Frame(self, bg=BG)
        cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=2)
        cols.columnconfigure(1, weight=3)
        cols.columnconfigure(2, weight=6)
        cols.rowconfigure(1, weight=1)
        for i, h in enumerate(("artists", "albums", "songs")):
            header(cols, h).grid(row=0, column=i, sticky="w", padx=(0, 12))
        fa, self.artists = tree(cols, [("name", "")], [200], "name", "browse")
        fb, self.albums = tree(cols, [("name", ""), ("n", "")], [220, 40], "name", "browse")
        fc, self.songs = tree(cols, [("num", "#"), ("title", "title"), ("artist", "artist"),
                                     ("time", "time")], [40, 300, 200, 60], "title")
        for i, f in enumerate((fa, fb, fc)):
            f.grid(row=1, column=i, sticky="nsew", padx=(0, 12))
        self.artists.bind("<<TreeviewSelect>>", lambda e: self.fill_albums())
        self.albums.bind("<<TreeviewSelect>>", lambda e: self.fill_songs())
        self.lib = {}

    def card_changed(self):
        if not self.app.card:
            self.lib = {}
            self.fill()

    def fill(self):
        self.lib = music.group(self.app.tracks)
        self.artists.delete(*self.artists.get_children())
        self.artists.insert("", "end", iid="*", values=("all artists",))
        for a in sorted(self.lib, key=str.lower):
            self.artists.insert("", "end", iid="a:" + a, values=(a,))
        self.artists.selection_set("*")
        self.fill_albums()

    def _artist(self):
        sel = self.artists.selection()
        return None if not sel or sel[0] == "*" else sel[0][2:]

    def fill_albums(self):
        self.albums.delete(*self.albums.get_children())
        a = self._artist()
        self.albums.insert("", "end", iid="*", values=("all albums", ""))
        pairs = [(a, al) for al in self.lib.get(a, {})] if a else \
                [(ar, al) for ar in self.lib for al in self.lib[ar]]
        for ar, al in sorted(pairs, key=lambda p: p[1].lower()):
            self.albums.insert("", "end", iid="b:%s\t%s" % (ar, al),
                               values=(al, len(self.lib[ar][al])))
        self.albums.selection_set("*")
        self.fill_songs()

    def visible_tracks(self):
        q = self.search.get().strip().lower()
        if q:
            return [t for t in self.app.tracks
                    if q in t.title.lower() or q in t.artist.lower() or q in t.album.lower()]
        sel = self.albums.selection()
        if sel and sel[0] != "*":
            ar, al = sel[0][2:].split("\t", 1)
            return self.lib[ar][al]
        a = self._artist()
        out = []
        for ar in ([a] if a else sorted(self.lib, key=str.lower)):
            for al in sorted(self.lib.get(ar, {}), key=str.lower):
                out += self.lib[ar][al]
        return out

    def fill_songs(self):
        self.songs.delete(*self.songs.get_children())
        for t in self.visible_tracks():
            self.songs.insert("", "end", iid=t.rel,
                              values=(t.num or "", t.title, t.artist, mmss(t.secs)))

    def selected(self):
        return list(self.songs.selection())

    def _import(self, paths):
        if not paths or not self.app.need_card():
            return
        card = self.app.card

        def work(report):
            return music.import_songs(card, paths, progress=lambda i, n, s: report(i, n, "copying " + s))

        def done(r):
            messagebox.showinfo("Game Zune", summary("songs", *r))
            self.app.reload_music()
        self.app.run(work, done, "adding songs")

    def add_files(self):
        if not self.app.need_card():
            return
        paths = filedialog.askopenfilenames(
            title="Songs to put on the card",
            filetypes=[("Music", " ".join("*" + e for e in music.AUDIO)), ("All files", "*.*")])
        self._import(list(paths))

    def add_folder(self):
        if not self.app.need_card():
            return
        d = filedialog.askdirectory(title="A folder of music (everything in it goes on)")
        if d:
            self._import([d])

    def delete(self):
        rels = self.selected()
        if not rels:
            messagebox.showinfo("Game Zune", "Choose the songs to delete in the songs list first.")
            return
        if not messagebox.askyesno("Game Zune", "Delete %d song%s from the card?\n\nThey are taken off "
                                   "your playlists and liked songs too." %
                                   (len(rels), "" if len(rels) == 1 else "s")):
            return
        card = self.app.card

        def work(report):
            gone = music.delete_songs(card, rels)
            playlists.forget(card, gone)
            return gone
        self.app.run(work, lambda gone: self.app.reload_music(), "deleting")

    def to_playlist(self):
        rels = self.selected()
        if not rels or not self.app.need_card():
            messagebox.showinfo("Game Zune", "Choose songs in the songs list first.")
            return
        mine = [p for p in playlists.all_playlists(self.app.card) if p.editable]
        names = [p.name for p in mine]
        name = ChoiceDialog(self, "add to playlist", "Add %d song%s to:" % (
            len(rels), "" if len(rels) == 1 else "s"), names, allow_new=True).result
        if not name:
            return
        try:
            pl = next((p for p in mine if p.name == name), None) or playlists.create(self.app.card, name)
        except ValueError as e:
            messagebox.showerror("Game Zune", str(e))
            return
        pl.songs += [r for r in rels if r not in pl.songs]
        pl.save(self.app.titles())
        self.app.pages["playlists"].reload(select=pl.name)
        self.app.set_status("added to %s" % pl.name)


# ---- playlists ----------------------------------------------------------------------

class PlaylistsPage(Page):
    def __init__(self, app):
        super().__init__(app)
        self.lists = []
        self.pl = None
        self.dirty = False
        left = tk.Frame(self, bg=BG)
        left.pack(side="left", fill="y", padx=(0, 18))
        header(left, "playlists").pack(anchor="w")
        f, self.names = tree(left, [("name", ""), ("kind", "")], [210, 70], "name", "browse")
        f.pack(fill="both", expand=True, pady=(4, 6))
        self.names.bind("<<TreeviewSelect>>", lambda e: self.pick())
        b = tk.Frame(left, bg=BG)
        b.pack(fill="x")
        ttk.Button(b, text="new", style="Accent.TButton", command=self.new).pack(side="left")
        ttk.Button(b, text="rename", command=self.rename).pack(side="left", padx=4)
        ttk.Button(b, text="copy", command=self.copy).pack(side="left")
        ttk.Button(b, text="delete", command=self.delete).pack(side="left", padx=4)

        right = tk.Frame(self, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        self.title_l = header(right, "")
        self.title_l.pack(anchor="w")
        self.note = ttk.Label(right, text="", style="Dim.TLabel", wraplength=560, justify="left")
        self.note.pack(anchor="w")
        f, self.songs = tree(right, [("i", "#"), ("title", "title"), ("artist", "artist"),
                                     ("time", "time")], [40, 240, 160, 56], "title")
        f.pack(fill="both", expand=True, pady=(4, 6))
        b = tk.Frame(right, bg=BG)
        b.pack(fill="x")
        self.edit_buttons = [
            ttk.Button(b, text="add songs...", command=self.add_songs),
            ttk.Button(b, text="remove", command=self.remove),
            ttk.Button(b, text="move up", command=lambda: self.move(-1)),
            ttk.Button(b, text="move down", command=lambda: self.move(1)),
        ]
        for w in self.edit_buttons:
            w.pack(side="left", padx=(0, 4))
        self.save_b = ttk.Button(b, text="save", style="Accent.TButton", command=self.save)
        self.save_b.pack(side="right")

    def card_changed(self):
        self.reload()

    def library_changed(self):
        self.reload(select=self.pl.name if self.pl else None)

    def shown(self):
        if self.app.card and not self.lists:
            self.reload()

    def reload(self, select=None):
        self.names.delete(*self.names.get_children())
        self.lists = playlists.all_playlists(self.app.card) if self.app.card else []
        kinds = {"liked": "♥ liked", "auto": "auto", "yours": ""}
        for i, p in enumerate(self.lists):
            self.names.insert("", "end", iid=str(i), values=(p.name, kinds[p.kind]))
        self.pl, self.dirty = None, False
        idx = next((i for i, p in enumerate(self.lists) if p.name == select), 0 if self.lists else None)
        if idx is not None:
            self.names.selection_set(str(idx))
        else:
            self.show_songs()

    def _leave(self):
        if self.dirty and self.pl and messagebox.askyesno(
                "Game Zune", "Save the changes to %s?" % self.pl.name):
            self.save()
        self.dirty = False

    def pick(self):
        sel = self.names.selection()
        if not sel:
            return
        new = self.lists[int(sel[0])]
        if new is self.pl:
            return
        self._leave()
        self.pl = new
        self.show_songs()

    def show_songs(self):
        self.songs.delete(*self.songs.get_children())
        pl = self.pl
        self.title_l.configure(text=pl.name if pl else "")
        if not pl:
            self.note.configure(text="")
            return
        note = {"liked": "the songs you liked on the Pixel 2 (Y on Now Playing). Adding and "
                         "removing here likes and unlikes them.",
                "auto": "made by update (on the device page) and rebuilt each time - "
                        "copy it to make one of your own.",
                "yours": ""}[pl.kind]
        if pl.kept:
            note += ("  " if note else "") + "%d line%s for songs not on the card are kept." % (
                len(pl.kept), "" if len(pl.kept) == 1 else "s")
        self.note.configure(text=note)
        for i, rel in enumerate(pl.songs):
            t = self.app.by_rel.get(rel)
            self.songs.insert("", "end", iid="%d" % i, values=(
                i + 1, t.title if t else rel.rsplit("/", 1)[-1], t.artist if t else "",
                mmss(t.secs) if t else ""))
        state = "!disabled" if pl.editable else "disabled"
        for w in self.edit_buttons + [self.save_b]:
            w.state([state])

    def _mark(self):
        self.dirty = True
        self.title_l.configure(text=self.pl.name + "  *")

    def add_songs(self):
        if not self.pl or not self.pl.editable:
            return
        picked = SongPicker(self, self.app.tracks).result
        if picked:
            self.pl.songs += [r for r in picked if r not in self.pl.songs or self.pl.kind != "liked"]
            self.show_songs()
            self._mark()

    def _sel(self):
        return sorted(int(i) for i in self.songs.selection())

    def remove(self):
        idx = self._sel()
        if not idx or not self.pl.editable:
            return
        self.pl.songs = [r for i, r in enumerate(self.pl.songs) if i not in idx]
        self.show_songs()
        self._mark()

    def move(self, d):
        idx = self._sel()
        if not idx or not self.pl.editable:
            return
        s = self.pl.songs
        order = idx if d < 0 else list(reversed(idx))
        if (d < 0 and idx[0] == 0) or (d > 0 and idx[-1] == len(s) - 1):
            return
        for i in order:
            s[i], s[i + d] = s[i + d], s[i]
        self.show_songs()
        self.songs.selection_set([str(i + d) for i in idx])
        self._mark()

    def save(self):
        if not self.pl or not self.pl.editable:
            return
        self.pl.save(self.app.titles())
        self.dirty = False
        self.title_l.configure(text=self.pl.name)
        self.app.set_status("saved %s" % self.pl.name)

    def new(self):
        if not self.app.need_card():
            return
        name = simpledialog.askstring("Game Zune", "Name of the new playlist:", parent=self)
        if not name:
            return
        self._leave()
        try:
            p = playlists.create(self.app.card, name)
        except ValueError as e:
            messagebox.showerror("Game Zune", str(e))
            return
        self.reload(select=p.name)

    def rename(self):
        if not self.pl:
            return
        if self.pl.kind != "yours":
            messagebox.showinfo("Game Zune", "liked songs and the auto playlists keep their names.")
            return
        name = simpledialog.askstring("Game Zune", "New name:", initialvalue=self.pl.name, parent=self)
        if not name or name == self.pl.name:
            return
        self._leave()
        try:
            p = playlists.rename(self.app.card, self.pl, name)
        except (ValueError, OSError) as e:
            messagebox.showerror("Game Zune", str(e))
            return
        self.reload(select=p.name)

    def copy(self):
        if not self.pl:
            return
        name = simpledialog.askstring("Game Zune", "Name of the copy:",
                                      initialvalue="my " + self.pl.name, parent=self)
        if not name:
            return
        self._leave()
        try:
            p = playlists.copy(self.app.card, self.pl, name)
        except ValueError as e:
            messagebox.showerror("Game Zune", str(e))
            return
        self.reload(select=p.name)

    def delete(self):
        if not self.pl:
            return
        warn = ("This is the record of your likes: deleting it unlikes every song in it.\n\n"
                if self.pl.kind == "liked" else
                "update will make it again.\n\n" if self.pl.kind == "auto" else "")
        if not messagebox.askyesno("Game Zune", "%sDelete the playlist %s? (The songs stay.)" %
                                   (warn, self.pl.name)):
            return
        playlists.delete(self.app.card, self.pl)
        self.reload()


# ---- games ---------------------------------------------------------------------------

class GamesPage(Page):
    def __init__(self, app):
        super().__init__(app)
        self.systems = []
        self.sys = None
        self.art_img = None
        piv = tk.Frame(self, bg=BG)
        piv.pack(fill="x")
        self.sys_row = piv
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", pady=8)
        ttk.Button(bar, text="add games...", style="Accent.TButton", command=self.add).pack(side="left")
        ttk.Button(bar, text="delete", command=self.delete).pack(side="left", padx=6)
        ttk.Button(bar, text="get missing box art", command=lambda: self.art(missing=True)).pack(side="left")
        ttk.Button(bar, text="get box art for these", command=lambda: self.art(missing=False)).pack(
            side="left", padx=6)
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)
        f, self.list = tree(body, [("game", "game"), ("art", "box art")], [520, 80], "game")
        f.pack(side="left", fill="both", expand=True)
        self.list.bind("<<TreeviewSelect>>", lambda e: self.preview())
        self.pic = tk.Label(body, bg=BG, fg=FAINT, text="", width=36, font=(FONT, 10))
        self.pic.pack(side="left", fill="y", padx=(18, 0))

    def card_changed(self):
        for w in self.sys_row.winfo_children():
            w.destroy()
        self.systems = games.systems(self.app.card) if self.app.card else []
        self.sys_labels = {}
        for s in self.systems:
            l = tk.Label(self.sys_row, text=s.name.lower(), bg=BG, fg=FAINT, font=(FONT, 16),
                         cursor="hand2")
            l.pack(side="left", padx=(0, 22))
            l.bind("<Button-1>", lambda e, s=s: self.pick(s))
            self.sys_labels[s.name] = l
        self.pick(self.systems[0] if self.systems else None)

    def pick(self, s):
        self.sys = s
        for n, l in getattr(self, "sys_labels", {}).items():
            l.configure(fg=FG if s and n == s.name else FAINT)
        self.fill()

    def fill(self):
        self.list.delete(*self.list.get_children())
        if not self.sys:
            return
        for rom in games.games(self.app.card, self.sys):
            self.list.insert("", "end", iid=rom, values=(
                os.path.splitext(rom)[0], "yes" if games.has_art(self.app.card, self.sys, rom) else "-"))
        self.preview()

    def preview(self):
        sel = self.list.selection()
        self.art_img = None
        if sel and self.sys:
            p = games.art_path(self.app.card, self.sys, sel[0])
            if os.path.exists(p):
                try:
                    img = tk.PhotoImage(file=p)
                    k = max(1, (max(img.width(), img.height()) + 279) // 280)
                    self.art_img = img.subsample(k, k)
                except tk.TclError:
                    self.art_img = None
        self.pic.configure(image=self.art_img or "", text="" if self.art_img else
                           ("no box art yet" if sel else ""))

    def add(self):
        if not self.app.need_card():
            return
        paths = filedialog.askopenfilenames(
            title="Game Boy, Game Boy Color and Game Boy Advance games",
            filetypes=[("Game Boy games", "*.gb *.gbc *.gba *.dmg *.cgb *.agb *.zip"),
                       ("All files", "*.*")])
        if not paths:
            return
        card = self.app.card

        def work(report):
            return games.import_roms(card, list(paths),
                                     progress=lambda i, n, s: report(i, n, "copying " + s))

        def done(r):
            messagebox.showinfo("Game Zune", summary("games", *r) +
                                "\n\nGet their box art with \"get missing box art\".")
            self.card_changed()
        self.app.run(work, done, "adding games")

    def delete(self):
        roms = list(self.list.selection())
        if not roms:
            return
        if messagebox.askyesno("Game Zune", "Delete %d game%s and their box art? Saves are kept." %
                               (len(roms), "" if len(roms) == 1 else "s")):
            games.delete_games(self.app.card, self.sys, roms)
            self.fill()

    def art(self, missing):
        if not self.sys or not self.app.need_card():
            return
        card, s = self.app.card, self.sys
        roms = games.games(card, s) if missing else list(self.list.selection())
        if missing:
            roms = [r for r in roms if not games.has_art(card, s, r)]
        if not roms:
            messagebox.showinfo("Game Zune", "Every game here has its box art." if missing
                                else "Choose games in the list first.")
            return

        def work(report):
            got = []
            for i, r in enumerate(roms):
                report(i, len(roms), "box art for " + os.path.splitext(r)[0])
                if games.fetch_art(card, s, r):
                    got.append(r)
            return got

        def done(got):
            miss = len(roms) - len(got)
            messagebox.showinfo("Game Zune", "Box art for %d game%s.%s" % (
                len(got), "" if len(got) == 1 else "s",
                "\n\n%d not found under their names: libretro names games the No-Intro way, "
                "e.g. \"Pokemon - Red Version (USA, Europe)\"." % miss if miss else ""))
            self.fill()
        self.app.run(work, done, "getting box art (needs the internet)")


# ---- the device --------------------------------------------------------------------

class DevicePage(Page):
    def __init__(self, app):
        super().__init__(app)
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x")
        header(top, "this card").grid(row=0, column=0, sticky="w")
        self.info = ttk.Label(top, text="", style="Dim.TLabel", justify="left")
        self.info.grid(row=1, column=0, sticky="w", pady=(2, 10))

        lf = tk.Frame(self, bg=BG)
        lf.pack(fill="x", pady=4)
        header(lf, "the zune theme").pack(anchor="w")
        ttk.Label(lf, text="the Zune launcher this app carries, put on the card - or the stock "
                  "one put back.", style="Dim.TLabel").pack(anchor="w")
        b = tk.Frame(lf, bg=BG)
        b.pack(anchor="w", pady=6)
        self.install_b = ttk.Button(b, text="install / update the zune theme", style="Accent.TButton",
                                    command=self.install)
        self.install_b.pack(side="left")
        self.restore_b = ttk.Button(b, text="restore the stock launcher", command=self.restore)
        self.restore_b.pack(side="left", padx=6)

        uf = tk.Frame(self, bg=BG)
        uf.pack(fill="x", pady=(14, 4))
        header(uf, "update").pack(anchor="w")
        ttk.Label(uf, text="real titles, genres and years for the Pixel 2, and the nine auto playlists "
                  "(chill, workout, dark wave ...) from public music databases.",
                  style="Dim.TLabel").pack(anchor="w")
        opts = tk.Frame(uf, bg=BG)
        opts.pack(anchor="w", pady=6)
        s = app.settings
        self.offline = tk.BooleanVar(value=s.get("offline", False))
        ttk.Checkbutton(opts, text="offline (what is already looked up)", variable=self.offline).pack(
            side="left")
        ttk.Label(opts, text="   Last.fm key", style="Dim.TLabel").pack(side="left")
        self.lf_key = tk.StringVar(value=s.get("lastfm_key", ""))
        ttk.Entry(opts, textvariable=self.lf_key, width=22).pack(side="left", padx=4)
        ttk.Label(opts, text="user", style="Dim.TLabel").pack(side="left")
        self.lf_user = tk.StringVar(value=s.get("lastfm_user", ""))
        ttk.Entry(opts, textvariable=self.lf_user, width=14).pack(side="left", padx=4)
        b = tk.Frame(uf, bg=BG)
        b.pack(anchor="w")
        ttk.Button(b, text="update library and auto playlists", style="Accent.TButton",
                   command=self.update).pack(side="left")
        ttk.Button(b, text="eject the card", command=self.eject).pack(side="left", padx=6)

        self.out = tk.Text(self, bg=PANEL, fg=DIM, insertbackground=FG, relief="flat", height=10,
                           font=("Consolas" if sys.platform == "win32" else "Courier", 9),
                           wrap="word", state="disabled")
        self.out.pack(fill="both", expand=True, pady=(12, 0))

    def card_changed(self):
        c = self.app.card
        if not c:
            self.info.configure(text="no card")
            return
        want = device.bundled_version()
        lines = ["%s" % c.root,
                 "TortOS %s   -   launcher: %s%s" % (
                     c.version(), "zune" if c.has_zune() else "stock",
                     "" if not want or want == c.version() else
                     "   (this app's zune launcher is for TortOS %s)" % want),
                 "%s free" % human_size(c.free_bytes())]
        self.info.configure(text="\n".join(lines))
        self.restore_b.state(["!disabled" if device.can_restore(c) else "disabled"])
        self.install_b.state(["!disabled" if device.bundled_launcher() else "disabled"])

    def shown(self):
        self.card_changed()

    def log(self, line):
        self.out.configure(state="normal")
        self.out.insert("end", line + "\n")
        self.out.see("end")
        self.out.configure(state="disabled")

    def _job(self, fn, what):
        if not self.app.need_card():
            return
        card = self.app.card

        def work(report):
            return fn(card)

        def done(notes):
            for n in notes:
                self.log(n)
            self.card_changed()
            messagebox.showinfo("Game Zune", "\n".join(notes))
        self.app.run(work, done, what)

    def install(self):
        self._job(device.install_theme, "installing the zune theme")

    def restore(self):
        if messagebox.askyesno("Game Zune", "Put the stock TortOS launcher back?"):
            self._job(device.restore_stock, "restoring the stock launcher")

    def update(self):
        if not self.app.need_card():
            return
        s = self.app.settings
        s.update(offline=self.offline.get(), lastfm_key=self.lf_key.get().strip(),
                 lastfm_user=self.lf_user.get().strip())
        save_settings(s)
        card = self.app.card
        events = self.app.events

        def work(report):
            device.update_library(card, lambda line: events.put(("log", line)),
                                  offline=s["offline"], lastfm_key=s["lastfm_key"],
                                  lastfm_user=s["lastfm_user"])

        def done(_):
            self.app.reload_music()
            messagebox.showinfo("Game Zune", "The library and the auto playlists are up to date.")
        self.log("--- update")
        self.app.run(work, done, "updating the library (this takes a while the first time)")

    def eject(self):
        if not self.app.need_card():
            return
        if self.app.busy:
            messagebox.showinfo("Game Zune", "Wait for %s to finish first." % self.app.busy)
            return
        if device.eject(self.app.card):
            messagebox.showinfo("Game Zune", "Ejected - take the card out and put it in the Pixel 2.")
            self.app.card = None
            self.app.refresh_cards()
        else:
            messagebox.showwarning("Game Zune", "The computer would not let go of the card. Close "
                                   "anything using it and try again, or eject it yourself.")


# ---- dialogs ---------------------------------------------------------------------------

class _Dialog(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=BG)
        self.transient(parent.winfo_toplevel())
        self.result = None

    def run(self):
        self.grab_set()
        self.wait_window(self)


class SongPicker(_Dialog):
    """Songs from the library, searched, several at once."""

    def __init__(self, parent, tracks):
        super().__init__(parent, "add songs")
        self.geometry("760x560")
        self.tracks = tracks
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=16, pady=12)
        ttk.Label(top, text="search", style="Dim.TLabel").pack(side="left")
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *a: self.fill())
        e = ttk.Entry(top, textvariable=self.q, width=40)
        e.pack(side="left", padx=8)
        e.focus_set()
        f, self.list = tree(self, [("title", "title"), ("artist", "artist"), ("album", "album")],
                            [300, 200, 200], "title")
        f.pack(fill="both", expand=True, padx=16)
        b = tk.Frame(self, bg=BG)
        b.pack(fill="x", padx=16, pady=12)
        ttk.Button(b, text="add", style="Accent.TButton", command=self.ok).pack(side="right")
        ttk.Button(b, text="cancel", command=self.destroy).pack(side="right", padx=6)
        self.list.bind("<Double-1>", lambda e: self.ok())
        self.fill()
        self.run()

    def fill(self):
        q = self.q.get().strip().lower()
        self.list.delete(*self.list.get_children())
        for t in self.tracks:
            if not q or q in t.title.lower() or q in t.artist.lower() or q in t.album.lower():
                self.list.insert("", "end", iid=t.rel, values=(t.title, t.artist, t.album))

    def ok(self):
        self.result = list(self.list.selection())
        self.destroy()


class ChoiceDialog(_Dialog):
    def __init__(self, parent, title, prompt, choices, allow_new=False):
        super().__init__(parent, title)
        ttk.Label(self, text=prompt).pack(anchor="w", padx=16, pady=(14, 6))
        self.var = tk.StringVar(value=choices[0] if choices else "")
        box = ttk.Combobox(self, textvariable=self.var, values=choices, width=40,
                           state="normal" if allow_new else "readonly")
        box.pack(padx=16)
        if allow_new:
            ttk.Label(self, text="(or type a new name)", style="Dim.TLabel").pack(anchor="w", padx=16)
        b = tk.Frame(self, bg=BG)
        b.pack(fill="x", padx=16, pady=12)
        ttk.Button(b, text="ok", style="Accent.TButton", command=self.ok).pack(side="right")
        ttk.Button(b, text="cancel", command=self.destroy).pack(side="right", padx=6)
        self.run()

    def ok(self):
        self.result = self.var.get().strip() or None
        self.destroy()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    App(argv[0] if argv else None).mainloop()


if __name__ == "__main__":
    main()
