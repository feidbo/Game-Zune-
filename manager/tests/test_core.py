"""The app's work, without its window: python -m unittest discover -s manager/tests"""
import io
import json
import os
import urllib.parse
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gamezune import albumart, card as C, device, gameinfo, games, match, music, playlists  # noqa: E402

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


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg to make songs")
class Featured(CardTest):
    def test_a_featured_artist_files_under_the_act(self):
        song(os.path.join(self.src, "a.mp3"), "Come Together", "The Beatles", "Abbey Road", track="1")
        song(os.path.join(self.src, "b.mp3"), "One Night", "The Beatles feat. Johnny", "One Night", track="1")
        added, _, _ = music.import_songs(self.card, [self.src])
        self.assertEqual(sorted(r.split("/")[1] for _, r in added), ["The Beatles", "The Beatles"])
        self.put("Music/Drake ft. Rihanna/Take Care/01 - Take Care.mp3")
        lib = music.group(music.scan(self.card, tags=False))
        self.assertEqual(sorted(lib), ["Drake", "The Beatles"])
        self.assertEqual(sorted(lib["The Beatles"]), ["Abbey Road", "One Night"])


class Disliked(CardTest):
    def test_what_the_pixel_disliked_comes_off(self):
        keep = ["Music/Blur/Parklife/01 - Girls.mp3", "Music/Beatles Tribute/One/01 - X.mp3"]
        go = ["Music/Blur/The Great Escape/01 - Stereotypes.mp3",
              "Music/The Beatles/Abbey Road/01 - Come Together.mp3",
              "Music/The Beatles feat. Johnny/One Night/01 - Song.mp3",
              "Music/Blur/Parklife/02 - Tracy Jacks.mp3"]
        for r in keep + go:
            self.put(r)
        self.put("Music/.zune/remove.tsv", ("# header\nalbum\tMusic/Blur/The Great Escape\n"
                                            "artist\tThe Beatles\n").encode())
        self.put("Music/.zune/ratings.tsv", b"Music/Blur/Parklife/02 - Tracy Jacks.mp3\t-1\n"
                                            b"Music/Gone/x.mp3\t-1\n")
        found = music.disliked(self.card)
        self.assertEqual(found["artists"], ["The Beatles"])
        self.assertEqual(found["rels"], sorted(go), "an act's 'feat.' folder goes with it, a tribute does not")
        gone = music.remove_disliked(self.card, found)
        self.assertEqual(sorted(gone), sorted(go))
        for r in keep:
            self.assertTrue(os.path.exists(self.card.full(r)))
        self.assertEqual(music.disliked(self.card)["rels"], [])
        self.assertNotIn("album", read(self.card.path("Music", ".zune", "remove.tsv")).replace("album<TAB>", ""))


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


class Matching(unittest.TestCase):
    def test_names_alike_and_not(self):
        L = match.loose
        self.assertEqual(L("The Bends (Collector's Edition)"), "bends")
        self.assertEqual(L("Abbey Road - 2019 Mix"), "abbey road")
        self.assertEqual(L("Legend of Zelda, The - Link's Awakening", music=False),
                         L("The Legend of Zelda: Link's Awakening", music=False))
        self.assertEqual(L("Final Fantasy Legend II"), "final fantasy legend 2")
        self.assertEqual(L("Pokemon - Red Version", music=False), "pokemon red version")
        self.assertGreaterEqual(match.similar(L("pokemon red"), L("pokemon red version")), 0.8)
        self.assertGreaterEqual(match.similar(L("ok computer"), L("OK Computer OKNOTOK 1997 2017")), 0.75)
        for want, got in (("tetris plus", "tetris"), ("super mario land 2", "super mario land"),
                          ("tetris", "tetris 2"), ("Greatest Hits Vol. 2", "Greatest Hits Vol. 1")):
            self.assertLess(match.similar(L(want), L(got)), 0.75, (want, got))
        self.assertTrue(match.same_artist("Beyonce", "Beyoncé"))
        self.assertTrue(match.same_artist("Daft Punk", "Daft Punk & Pharrell Williams"))
        self.assertFalse(match.same_artist("Rem", "Remy Ma"))


def jpeg(side=900):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (side, side), (200, 0, 140)).save(b, "JPEG")
    return b.getvalue()


class FakeMusicWeb:
    """Deezer and iTunes as they answer: everything they hold for any search,
    for the matching to sort out, the way a real search returns near misses."""
    ALBUMS = [("Discovery", "Daft Punk", "https://img/discovery.jpg"),
              ("The Bends (Collector's Edition)", "Radiohead", "https://img/bends.jpg"),
              ("Greatest Hits Vol. 1", "Queen", "https://img/gh1.jpg")]
    SONGS = [("Blinding Lights", "The Weeknd", "https://img/afterhours.jpg")]
    ITUNES = [("folklore", "Taylor Swift", "https://img/folklore/100x100bb.jpg")]

    def __init__(self):
        self.asked = []

    def __call__(self, url):
        self.asked.append(url)
        if url.startswith("https://img/"):
            return jpeg()
        if "api.deezer.com/search/album" in url:
            return json.dumps({"data": [{"title": t, "artist": {"name": a}, "cover_xl": p}
                                        for t, a, p in self.ALBUMS]}).encode()
        if "api.deezer.com/search" in url:
            return json.dumps({"data": [{"title": t, "artist": {"name": a}, "album": {"cover_xl": p}}
                                        for t, a, p in self.SONGS]}).encode()
        if "itunes.apple.com" in url:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            key = "collectionName" if q["entity"] == ["album"] else "trackName"
            return json.dumps({"results": [{key: t, "artistName": a, "artworkUrl100": p}
                                           for t, a, p in self.ITUNES]}).encode()
        return None


class AlbumArt(CardTest):
    def test_strict_then_broader_then_by_song(self):
        for rel in ("Music/Daft Punk/Discovery/01 - One More Time.mp3",
                    "Music/Radiohead/The Bends/01 - Planet Telex.mp3",
                    "Music/The Weeknd/Unknown Album/01 - Blinding Lights.mp3",
                    "Music/Taylor Swift/folklore/01 - the 1.mp3",
                    "Music/Queen/Greatest Hits Vol. 2/01 - A Kind of Magic.mp3",
                    "Music/Someone Else/Discovery/01 - Other.mp3",
                    "Music/Local/Album/01 - Song.mp3", "Music/Local/Album/back.png",
                    "Music/Loose song.mp3",
                    "Music/Has/Cover/01 - Song.mp3", "Music/Has/Cover/folder.jpg"):
            self.put(rel, jpeg(10) if rel.endswith((".jpg", ".png")) else b"x")
        self.put("Music/Local/Album/front.jpg", jpeg(10))
        web = FakeMusicWeb()
        tracks = music.scan(self.card, tags=False)
        todo = [rel for rel, *_ in music.albums_without_covers(self.card, tracks)]
        self.assertNotIn("Music", todo, "loose songs are no album")
        self.assertNotIn("Music/Has/Cover", todo)
        got, missing = music.get_covers(self.card, tracks, finder=albumart.Finder(web, pace=False))
        self.assertEqual(dict(got), {"Music/Daft Punk/Discovery": "exact",
                                     "Music/Radiohead/The Bends": "close",
                                     "Music/The Weeknd/Unknown Album": "by song",
                                     "Music/Taylor Swift/folklore": "exact",
                                     "Music/Local/Album": "from its files"})
        self.assertEqual(sorted(missing), ["Music/Queen/Greatest Hits Vol. 2", "Music/Someone Else/Discovery"],
                         "never another volume, nor another artist's album")
        from PIL import Image
        cover = self.card.full("Music/Daft Punk/Discovery/cover.jpg")
        with Image.open(cover) as im:
            self.assertEqual(im.size, (albumart.SIDE, albumart.SIDE))
        self.assertTrue(any("600x600bb" in u for u in web.asked), "iTunes art asked for big")
        self.assertTrue(music.has_cover(self.card, "Music/Local/Album"))
        self.assertEqual(music.get_covers(self.card, music.scan(self.card, tags=False),
                                          finder=albumart.Finder(web, pace=False))[0], [],
                         "a second run finds only what is still missing")


class BroaderBoxArt(CardTest):
    NAMES = ["Tetris (World) (Rev 1)", "Tetris 2 (USA, Europe)", "Pokemon - Red Version (USA, Europe)",
             "Pokemon - Red Version (Japan)", "Super Mario Land (World)",
             "Super Mario Land 2 - 6 Golden Coins (USA, Europe)", "Final Fantasy Legend II (USA)",
             "Legend of Zelda, The - Link's Awakening (USA, Europe)"]

    def test_close_names(self):
        for rom, want in (("Pokemon Red.gb", "Pokemon - Red Version (USA, Europe)"),
                          ("pokemon_red.gb", "Pokemon - Red Version (USA, Europe)"),
                          ("Super Mario Land 2.gb", "Super Mario Land 2 - 6 Golden Coins (USA, Europe)"),
                          ("Final Fantasy Legend 2 (U) [!].gb", "Final Fantasy Legend II (USA)"),
                          ("The Legend of Zelda - Links Awakening.gb",
                           "Legend of Zelda, The - Link's Awakening (USA, Europe)"),
                          ("Tetris Plus (USA).gb", None), ("Tetris 3.gb", None), ("Mario.gb", None)):
            self.assertEqual(games.close_match(rom, self.NAMES), want, rom)

    def test_broader_then_the_other_game_boy(self):
        png = io.BytesIO()
        __import__("PIL.Image").Image.new("RGB", (8, 8)).save(png, "PNG")
        lists = {"Nintendo%20-%20Game%20Boy/Named_Boxarts/": self.NAMES + [
                     "Pokemon - Yellow Version - Special Pikachu Edition (USA, Europe) (CGB+SGB Enhanced)"],
                 "Nintendo%20-%20Game%20Boy%20Color/Named_Boxarts/": ["Tetris DX (World)"]}
        asked = []

        def fake(url):
            asked.append(url)
            for k, names in lists.items():
                if url.endswith(k):
                    return ("".join('<a href="%s.png">x</a>' % urllib.parse.quote(n) for n in names)).encode()
            ok = ("Nintendo_-_Game_Boy/master/Named_Boxarts/Pokemon%20-%20Red%20Version%20%28USA%2C%20Europe%29",
                  "Nintendo_-_Game_Boy/master/Named_Boxarts/Pokemon%20-%20Yellow")
            return png.getvalue() if any(k in url for k in ok) else None
        games._index_cache.clear()
        gb = games.System("Game Boy", "Game Boy", ("gb",))
        gbc = games.System("Game Boy Color", "Game Boy Color", ("gbc",))
        self.assertEqual(games.fetch_art(self.card, gb, "Pokemon Red.gb", fetch=fake), "close")
        self.assertEqual(games.fetch_art(self.card, gbc, "Pokemon Yellow.gbc", fetch=fake), "other system")
        self.assertTrue(games.has_art(self.card, gbc, "Pokemon Yellow.gbc"))
        self.assertIsNone(games.fetch_art(self.card, gb, "Tetris Plus.gb", fetch=fake))
        games._index_cache.clear()


class FakeWiki:
    """Wikipedia and Wikidata as they answer, for one Game Boy Advance game
    and a series article that must not be taken for it."""
    def claim(v):
        return {"mainsnak": {"snaktype": "value", "datavalue": {"value": v}}}
    ITEMS = {
        "Q9": {"labels": {"en": {"value": "Metroid"}},
               "claims": {"P31": [claim({"id": "Q7058673"})], "P400": [claim({"id": "Q188642"})]}},
        "Q1": {"labels": {"en": {"value": "Metroid Fusion"}},
               "claims": {"P31": [claim({"id": "Q7889"})], "P400": [claim({"id": "Q188642"})],
                          "P577": [claim({"time": "+2002-11-17T00:00:00Z"}),
                                   claim({"time": "+2014-04-03T00:00:00Z"})],
                          "P136": [claim({"id": "Q2"})], "P178": [claim({"id": "Q3"})],
                          "P123": [claim({"id": "Q4"})]}},
        "Q5": {"labels": {"en": {"value": "Tetris"}},
               "claims": {"P31": [claim({"id": "Q7889"})], "P400": [claim({"id": "Q186437"})]}},
        "Q2": {"labels": {"en": {"value": "Metroidvania video game"}}},
        "Q3": {"labels": {"en": {"value": "Nintendo R&D1"}}},
        "Q4": {"labels": {"en": {"value": "Nintendo"}}},
    }
    TEXT = ("Metroid Fusion is a 2002 action-adventure game for the Game Boy Advance.\n"
            "Samus explores a space station.\n== Development ==\n"
            "The game was originally titled Metroid IV during development, its working title.\n"
            "== Reception ==\nCritics praised it.")
    WIKITEXT = "{{Infobox}}\n{{Video game reviews\n| MC = 92/100<ref>x</ref>\n| GR = 91%\n}}"

    def __call__(self, url):
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        if q.get("generator") == "search":
            pages = [{"title": "Metroid (video game series)", "index": 1, "pageprops": {"wikibase_item": "Q9"}},
                     {"title": "Metroid Fusion", "index": 2, "pageprops": {"wikibase_item": "Q1"}},
                     {"title": "Tetris (Game Boy video game)", "index": 3, "pageprops": {"wikibase_item": "Q5"}}]
            return json.dumps({"query": {"pages": pages}}).encode()
        if q.get("action") == "wbgetentities":
            return json.dumps({"entities": {i: self.ITEMS[i] for i in q["ids"].split("|")
                                            if i in self.ITEMS}}).encode()
        if q.get("prop") == "extracts":
            return json.dumps({"query": {"pages": [{"extract": self.TEXT}]}}).encode()
        if q.get("prop") == "revisions":
            return json.dumps({"query": {"pages": [{"revisions": [
                {"slots": {"main": {"content": self.WIKITEXT}}}]}]}}).encode()
        return None


class GameInfo(CardTest):
    def test_names_as_a_search_says_them(self):
        self.assertEqual(gameinfo.rom_title("Legend of Zelda, The - Link's Awakening DX (USA, Europe) (Rev 2).gbc"),
                         "The Legend of Zelda Link's Awakening DX")
        self.assertEqual(gameinfo.rom_title("pokemon_red.gb"), "pokemon red")

    def test_the_review_table_for_this_system(self):
        t = gameinfo.review_table("{{Video game reviews|MC = GBA: 85/100<br />PS2: 80/100|GR=88.5%"
                                  "|IGN = 9 out of 10}}", "Game Boy Advance")
        self.assertEqual(gameinfo.score_label(t), "metacritic 85")
        t = gameinfo.review_table("{{Video game reviews|MC = PS2: 80/100|GR=88.5%}}", "Game Boy Advance")
        self.assertEqual(gameinfo.score_label(t), "gamerankings 89%", "another system's Metacritic is not this one's")
        self.assertEqual(gameinfo.score_label({}), "")

    def test_found_read_and_kept_on_the_card(self):
        web = FakeWiki()
        gba = games.System("Game Boy Advance", "Game Boy Advance", ("gba",))
        self.put("Roms/Game Boy Advance/Metroid Fusion (USA).gba")
        found, missing = gameinfo.fetch(self.card, gba, ["Metroid Fusion (USA).gba", "Golden Sun (USA).gba"],
                                        wiki=gameinfo.Wiki(web, pace=False))
        self.assertEqual(found, ["Metroid Fusion (USA).gba"])
        self.assertEqual(missing, ["Golden Sun (USA).gba"], "never the series, never a Game Boy game")
        row = gameinfo.load(self.card)[("Game Boy Advance", "Metroid Fusion (USA).gba")]
        self.assertEqual((row["year"], row["genre"], row["developer"], row["publisher"], row["score"]),
                         ("2002", "metroidvania", "Nintendo R&D1", "Nintendo", "metacritic 92"))
        self.assertIn("Samus explores", row["synopsis"])
        self.assertIn("working title", row["fact"])
        self.assertEqual(row["source"], "Metroid Fusion")
        text = read(self.card.path("Roms", ".zune", "games.tsv"))
        self.assertEqual(len([ln for ln in text.splitlines() if not ln.startswith("#")]), 2,
                         "one line a game, the one not found kept so it is not asked again")
        self.assertTrue(gameinfo.has_info(gameinfo.load(self.card), "Game Boy Advance", "Metroid Fusion (USA).gba"))
        self.assertFalse(gameinfo.has_info(gameinfo.load(self.card), "Game Boy Advance", "Golden Sun (USA).gba"))

    def test_newlines_and_tabs_survive_the_file(self):
        rows = {("GB", "a.gb"): dict(dict.fromkeys(gameinfo.COLUMNS, ""), folder="GB", file="a.gb",
                                     synopsis="one\ntwo\tthree \\ four", source="A")}
        gameinfo.save(self.card, rows)
        self.assertEqual(gameinfo.load(self.card)[("GB", "a.gb")]["synopsis"], "one\ntwo three \\ four")


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
