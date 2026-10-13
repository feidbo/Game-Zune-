"""The app's work, without its window: python -m unittest discover -s manager/tests"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gamezune import card as C, device, games, music, playlists  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def read(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


def song(path, title=None, artist=None, album=None, albumartist=None, track=None, secs=1):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    meta = []
    for k, v in (("title", title), ("artist", artist), ("album", album),
                 ("album_artist", albumartist), ("track", track)):
        if v is not None:
            meta += ["-metadata", "%s=%s" % (k, v)]
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=22050:cl=mono", "-t", str(secs)] + meta + ["-q:a", "9", path],
                   check=True)


class CardTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="gz-card-")
        os.makedirs(os.path.join(self.root, "TortOS"))
        with open(os.path.join(self.root, "TortOS", "tortos.elf"), "wb") as f:
            f.write(b"\x7fELF stock launcher")
        with open(os.path.join(self.root, "TortOS", "VERSION"), "w") as f:
            f.write("1.6.0\n")
        self.card = C.Card(self.root)
        self.src = tempfile.mkdtemp(prefix="gz-src-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.src, ignore_errors=True)

    def put(self, rel, data=b"x"):
        p = self.card.full(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        return p


class Basics(CardTest):
    def test_a_card_is_known_by_its_launcher(self):
        self.assertTrue(C.is_card(self.root))
        self.assertFalse(C.is_card(self.src))
        self.assertEqual(self.card.version(), "1.6.0")
        self.assertFalse(self.card.has_zune())

    def test_names_every_card_takes(self):
        self.assertEqual(C.safe_name('AC/DC: "Live"?'), "AC_DC_ _Live__")
        self.assertEqual(C.safe_name("Trailing dots..."), "Trailing dots")
        self.assertEqual(C.safe_name("CON"), "_CON")
        self.assertEqual(C.safe_name(""), "Unknown")


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg to make songs")
class Music(CardTest):
    def test_songs_go_where_the_pixel_2_looks(self):
        a = os.path.join(self.src, "rip")
        song(os.path.join(a, "track1.mp3"), "Digital Love", "Daft Punk", "Discovery", "Daft Punk", "3")
        song(os.path.join(a, "track2.mp3"), "Feat Song", "Daft Punk feat. X", "Discovery", "Daft Punk", "4/14")
        with open(os.path.join(a, "folder.jpg"), "wb") as f:
            f.write(b"\xff\xd8\xff jpeg")
        song(os.path.join(self.src, "loose", "05 - No Tags.mp3"))
        added, skipped, failed = music.import_songs(self.card, [self.src])
        self.assertEqual(failed, [])
        rels = sorted(r for _, r in added)
        self.assertEqual(rels, ["Music/Daft Punk/Discovery/03 - Digital Love.mp3",
                                "Music/Daft Punk/Discovery/04 - Feat Song.mp3",
                                "Music/Unknown Artist/loose/05 - No Tags.mp3"])
        self.assertTrue(os.path.exists(self.card.full("Music/Daft Punk/Discovery/cover.jpg")))
        again = music.import_songs(self.card, [self.src])
        self.assertEqual((len(again[0]), len(again[1])), (0, 3), "the same songs are not copied twice")

        tracks = music.scan(self.card)
        lib = music.group(tracks)
        self.assertEqual([t.title for t in lib["Daft Punk"]["Discovery"]], ["Digital Love", "Feat Song"])
        self.assertEqual(lib["Daft Punk"]["Discovery"][0].secs, 1)

        gone = music.delete_songs(self.card, [r for r in rels if "Daft" in r])
        self.assertEqual(len(gone), 2)
        self.assertFalse(os.path.exists(self.card.full("Music/Daft Punk")),
                         "an emptied album goes, cover and all")

    def test_a_different_song_by_the_same_name_is_kept_too(self):
        song(os.path.join(self.src, "a", "x.mp3"), "Intro", "Band", "Album", track="1", secs=1)
        song(os.path.join(self.src, "b", "x.mp3"), "Intro", "Band", "Album", track="1", secs=2)
        added, _, _ = music.import_songs(self.card, [self.src])
        self.assertEqual(sorted(r for _, r in added), ["Music/Band/Album/01 - Intro (2).mp3",
                                                       "Music/Band/Album/01 - Intro.mp3"])

    def test_update_runs_offline(self):
        song(os.path.join(self.src, "s.mp3"), "Song", "Artist", "Album", track="1")
        music.import_songs(self.card, [self.src])
        lines = []
        device.update_library(self.card, lines.append, offline=True)
        self.assertTrue(any("library.tsv" in l for l in lines), lines)
        self.assertTrue(os.path.exists(self.card.full("Music/.zune/library.tsv")))


class Playlists(CardTest):
    def setUp(self):
        super().setUp()
        self.a = "Music/Art/Rec/01 - One.mp3"
        self.b = "Music/Art/Rec/02 - Two.mp3"
        self.put(self.a)
        self.put(self.b)

    def test_made_saved_and_read_back(self):
        p = playlists.create(self.card, "road trip")
        p.songs = [self.b, self.a]
        p.save({self.a: (61, "One - Art")})
        text = read(p.path)
        self.assertIn("#EXTINF:61,One - Art\n../Music/Art/Rec/01 - One.mp3", text)
        q = playlists.all_playlists(self.card)[0]
        self.assertEqual((q.name, q.kind, q.songs), ("road trip", "yours", [self.b, self.a]))
        with self.assertRaises(ValueError):
            playlists.create(self.card, "road trip")

    def test_lines_from_another_computer(self):
        p = self.put("Playlists/mine.m3u", (
            "#EXTM3U\r\nC:\\Users\\me\\music\\Art\\Rec\\01 - One.mp3\r\n"
            "file:///Users/me/Music/Art/Rec/02%20-%20Two.mp3\r\n"
            "D:\\Gone\\Missing.mp3\r\n").encode("utf-8"))
        pl = playlists.Playlist(self.card, p)
        self.assertEqual(pl.songs, [self.a, self.b])
        self.assertEqual(pl.kept, ["D:\\Gone\\Missing.mp3"])
        pl.save()
        self.assertIn("D:\\Gone\\Missing.mp3", read(p),
                      "a song off the card keeps its line")

    def test_three_kinds(self):
        self.put("Playlists/chill.m3u8", b"#EXTM3U\n# made by Game Zune zunesync - x\n../" + self.a.encode() + b"\n")
        self.put("Playlists/liked songs.m3u8", b"#EXTM3U\n../" + self.a.encode() + b"\n../" + self.a.encode() + b"\n")
        kinds = {p.name: p for p in playlists.all_playlists(self.card)}
        self.assertEqual(kinds["chill"].kind, "auto")
        self.assertFalse(kinds["chill"].editable)
        self.assertEqual(kinds["liked songs"].kind, "liked")
        self.assertEqual(kinds["liked songs"].songs, [self.a], "a song is liked once")
        self.assertEqual(playlists.all_playlists(self.card)[0].name, "liked songs")
        mine = playlists.copy(self.card, kinds["chill"], "my chill")
        self.assertEqual((mine.kind, mine.songs), ("yours", [self.a]))
        kinds["liked songs"].save()
        self.assertIn(playlists.LIKED_HEADER, read(kinds["liked songs"].path))

    def test_rename_takes_its_cover_and_forget_takes_songs_off(self):
        p = playlists.create(self.card, "old")
        p.songs = [self.a, self.b]
        p.save()
        self.put("Playlists/.media/old.jpg")
        q = playlists.rename(self.card, p, "new")
        self.assertTrue(os.path.exists(self.card.full("Playlists/.media/new.jpg")))
        playlists.forget(self.card, [self.a])
        self.assertEqual(playlists.Playlist(self.card, q.path).songs, [self.b])
        playlists.delete(self.card, playlists.Playlist(self.card, q.path))
        self.assertEqual(playlists.all_playlists(self.card), [])


class Games(CardTest):
    def test_roms_go_to_their_systems(self):
        for n in ("Tetris (World).gb", "Pokemon - Gold Version (USA, Europe).gbc", "Mother 3 (Japan).gba",
                  "notes.txt"):
            with open(os.path.join(self.src, n), "wb") as f:
                f.write(b"rom")
        with zipfile.ZipFile(os.path.join(self.src, "Zelda (USA).zip"), "w") as z:
            z.writestr("Zelda (USA).gbc", b"rom")
        added, skipped, failed = games.import_roms(self.card, [self.src])
        self.assertEqual(sorted(w for _, w in added), [
            "Game Boy Advance/Mother 3 (Japan).gba", "Game Boy Color/Pokemon - Gold Version (USA, Europe).gbc",
            "Game Boy Color/Zelda (USA).zip", "Game Boy/Tetris (World).gb"])
        self.assertEqual([os.path.basename(s) for s, _ in skipped], ["notes.txt"])
        gbc = [s for s in games.systems(self.card) if s.name == "Game Boy Color"][0]
        self.assertEqual(games.games(self.card, gbc), ["Pokemon - Gold Version (USA, Europe).gbc",
                                                       "Zelda (USA).zip"])

    def test_box_art_under_the_roms_name(self):
        from PIL import Image
        big = io.BytesIO()
        Image.new("RGB", (1000, 900), (200, 0, 140)).save(big, "PNG")
        asked = []

        def fake(url):
            asked.append(url)
            return big.getvalue() if url.endswith("/Tetris%20%28World%29.png") else None
        gb = games.System("Game Boy", "Game Boy", ("gb",))
        self.put("Roms/Game Boy/Tetris (World) [!].gb", b"rom")
        self.assertTrue(games.fetch_art(self.card, gb, "Tetris (World) [!].gb", fetch=fake))
        self.assertEqual(len(asked), 2, "its own name first, then without the [!]")
        art = games.art_path(self.card, gb, "Tetris (World) [!].gb")
        self.assertTrue(art.endswith(os.path.join("Roms", "Game Boy", ".media", "Tetris (World) [!].png")))
        self.assertLessEqual(max(Image.open(art).size), games.ART_SIDE)
        self.assertEqual(games.thumb_names("A&B: C?.gba")[0], "A_B_ C_")
        games.delete_games(self.card, gb, ["Tetris (World) [!].gb"])
        self.assertFalse(os.path.exists(art))


class ArtNames(CardTest):
    NAMES = ["Tetris (World) (Rev 1)", "Tetris (Japan)", "Tetris 2 (USA, Europe)", "Tetris DX (World)",
             "Pokemon - Red Version (USA, Europe)"]

    def test_the_closest_name_and_never_another_game(self):
        self.assertEqual(games.best_match("Tetris (World).gb", self.NAMES), "Tetris (World) (Rev 1)")
        self.assertEqual(games.best_match("Tetris 2 (USA).gb", self.NAMES), "Tetris 2 (USA, Europe)")
        self.assertEqual(games.best_match("Pokemon - Red Version (USA, Europe) (SGB Enhanced).gb",
                                          self.NAMES), "Pokemon - Red Version (USA, Europe)")
        self.assertIsNone(games.best_match("Tetris Plus (USA).gb", self.NAMES))

    def test_looked_up_when_not_under_its_own_name(self):
        from PIL import Image
        png = io.BytesIO()
        Image.new("RGB", (8, 8)).save(png, "PNG")
        listing = ("<html>" + "".join('<a href="%s.png">x</a>' % n.replace(" ", "%20")
                                      for n in self.NAMES) + "</html>").encode()

        def fake(url):
            if "thumbnails.libretro.com" in url:
                return listing
            return png.getvalue() if url.endswith("/Tetris%20%28World%29%20%28Rev%201%29.png") else None
        games._index_cache.clear()
        gb = games.System("Game Boy", "Game Boy", ("gb",))
        self.assertTrue(games.fetch_art(self.card, gb, "Tetris (World).gb", fetch=fake))
        games._index_cache.clear()


class Theme(CardTest):
    def setUp(self):
        super().setUp()
        self.bundle = os.path.join(self.src, "TortOS")
        os.makedirs(os.path.join(self.bundle, "fonts"))
        for rel, data in (("tortos.elf", b"\x7fELF zune " + C.ZUNE_MARK), ("ZUNE_FOR_VERSION", b"1.6.0\n"),
                          ("zune-wallpaper.jpg", b"jpg"), ("fonts/zune-light.ttf", b"ttf")):
            with open(os.path.join(self.bundle, rel), "wb") as f:
                f.write(data)
        self._b = device.bundled_launcher
        device.bundled_launcher = lambda: self.bundle

    def tearDown(self):
        device.bundled_launcher = self._b
        super().tearDown()

    def test_install_keeps_stock_once_and_restore_checks_the_version(self):
        device.install_theme(self.card)
        self.assertTrue(self.card.has_zune())
        stock = self.card.full("TortOS/tortos.elf.stock")
        self.assertEqual(read(stock, "rb"), b"\x7fELF stock launcher")
        device.install_theme(self.card)
        self.assertEqual(read(stock, "rb"), b"\x7fELF stock launcher", "never a Zune one as stock")
        with open(self.card.full("TortOS/VERSION"), "w") as f:
            f.write("9.9.9\n")
        with self.assertRaises(RuntimeError):
            device.restore_stock(self.card)
        with self.assertRaises(RuntimeError):
            device.install_theme(self.card)
        with open(self.card.full("TortOS/VERSION"), "w") as f:
            f.write("1.6.0\n")
        device.restore_stock(self.card)
        self.assertFalse(self.card.has_zune())


if __name__ == "__main__":
    unittest.main()
