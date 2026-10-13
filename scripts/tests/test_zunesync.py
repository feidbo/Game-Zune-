"""zunesync against a fake web: run with  python3 -m unittest discover scripts/tests

Builds a small card of silent, tagged MP3s named after real songs, answers
MusicBrainz, ListenBrainz and Deezer the way those services answer, and
checks each playlist gets the songs it should. Billboard is the real Hot 100
archive when BILLBOARD_CSV points at a copy (it is 20 MB, so not in the
repo); otherwise a few rows of it.
"""
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unicodedata
import urllib.parse
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import zunesync  # noqa: E402

# artist, title, year, MusicBrainz tags, Deezer bpm, listeners, Deezer rank
SONGS = [
    ("Depeche Mode", "Enjoy the Silence", 1990, ["synth-pop", "new wave"], 113, 900000, 800000),
    ("New Order", "Blue Monday", 1983, ["synth-pop", "new wave", "post-punk"], 130, 800000, 780000),
    ("Boy Harsher", "Pain", 2016, ["darkwave", "coldwave"], 120, 90000, 300000),
    ("Eiffel 65", "Blue (Da Ba Dee)", 1998, ["eurodance", "europop"], 128, 700000, 850000),
    ("Vengaboys", "We Like to Party!", 1998, ["eurodance", "europop", "dance-pop"], 137, 300000, 600000),
    ("Miles Davis", "So What", 1959, ["jazz", "modal jazz", "cool jazz"], 136, 400000, 600000),
    ("Norah Jones", "Don't Know Why", 2002, ["vocal jazz", "pop"], 88, 600000, 700000),
    ("OutKast", "Hey Ya!", 2003, ["hip hop", "pop rap"], 159, 1200000, 900000),
    ("Usher", "Yeah!", 2004, ["contemporary r&b", "crunk"], 105, 900000, 850000),
    ("Bon Iver", "Skinny Love", 2007, ["indie folk", "chill", "acoustic"], 76, 800000, 700000),
    ("The xx", "Intro", 2009, ["instrumental", "indie"], 100, 600000, 650000),
    ("Darude", "Sandstorm", 1999, ["trance", "eurodance"], 136, 500000, 750000),
    ("The Prodigy", "Breathe", 1996, ["big beat", "electronic"], 136, 300000, 600000),
    ("Johann Sebastian Bach", "Cello Suite No. 1", 2005, ["classical", "baroque"], 0, 200000, 500000),
    ("Nobody Knows", "Basement Demo", 2008, [], 0, 0, 0),
    ("Mazzy Star", "Fade Into You", 1993, ["dream pop", "mellow"], 0, 500000, 600000),
]

HOT100_FALLBACK = """chart_week,current_week,title,performer,last_week,peak_pos,wks_on_chart,wks_at_no1
2000-01-22,6,Blue (Da Ba Dee),Eiffel 65,8,6,20,NA
1999-03-27,26,We Like To Party! (The Vengabus),Vengaboys,30,26,20,NA
2004-02-14,1,Hey Ya!,OutKast,1,1,29,9
2004-03-27,1,Yeah!,Usher Featuring Lil Jon & Ludacris,1,1,40,12
1990-05-19,8,Enjoy The Silence,Depeche Mode,9,8,20,NA
2002-09-07,30,Don't Know Why,Norah Jones,31,30,20,NA
"""


class FakeNet(zunesync.Net):
    def __init__(self):
        super().__init__(offline=False)
        self.calls = []
        self.by_title = {zunesync.clean_title(s[1]): s for s in SONGS}

    def _song(self, title):
        return self.by_title.get(zunesync.clean_title(title))

    def json(self, url, params=None, gap=0.2, body=None):
        self.calls.append(url)
        params = params or {}
        if "musicbrainz.org/ws/2/recording" in url and "query" in params:
            q = params["query"]
            title = q.split('recording:"', 1)[1].split('"', 1)[0]
            s = self._song(title)
            if not s or not s[3]:
                return {"recordings": []}
            mbid = "mbid-" + zunesync.fold(s[1]).replace(" ", "-")
            return {"recordings": [
                {"id": mbid, "score": 100, "title": s[1], "length": 180000,
                 "first-release-date": "%d-03-01" % s[2],
                 "artist-credit": [{"name": s[0], "joinphrase": "",
                                    "artist": {"id": "art-" + zunesync.fold(s[0]).replace(" ", "-"),
                                               "name": s[0]}}],
                 "tags": [{"count": 3, "name": t} for t in s[3][1:]]},
                # A later compilation copy of the same song, which must not
                # move the year forward.
                {"id": mbid + "-comp", "score": 95, "title": s[1], "length": 181000,
                 "first-release-date": "%d" % (s[2] + 12),
                 "artist-credit": [{"name": s[0], "joinphrase": ""}]},
            ]}
        if "musicbrainz.org/ws/2/artist/" in url:
            name = url.rsplit("/", 1)[1][4:].replace("-", " ")
            s = next((x for x in SONGS if zunesync.fold(x[0]) == name), None)
            return {"genres": [{"name": s[3][0], "count": 5}] if s and s[3] else [], "tags": []}
        if "listenbrainz.org/1/popularity/recording" in url:
            out = []
            for m in body["recording_mbids"]:
                s = next((x for x in SONGS if "mbid-" + zunesync.fold(x[1]).replace(" ", "-") == m), None)
                out.append({"recording_mbid": m, "total_listen_count": s[5] * 10 if s else None,
                            "total_user_count": s[5] if s else None})
            return out
        if "api.deezer.com/search" in url:
            q = params["q"]
            title = q.split('track:"', 1)[1].split('"', 1)[0]
            s = self._song(title)
            if not s or not s[6]:
                return {"data": [], "total": 0}
            return {"data": [{"id": abs(hash(s[1])) % 10 ** 9, "title": s[1], "rank": s[6],
                              "duration": 180, "artist": {"name": s[0]}}], "total": 1}
        if "api.deezer.com/track/" in url:
            tid = int(url.rsplit("/", 1)[1])
            s = next((x for x in SONGS if abs(hash(x[1])) % 10 ** 9 == tid), None)
            return {"id": tid, "bpm": float(s[4]) if s else 0, "release_date": "%d-01-01" % (s[2] + 1) if s else ""}
        return None

    def download(self, url, out):
        src = os.environ.get("BILLBOARD_CSV")
        if src and os.path.exists(src):
            shutil.copy(src, out)
        else:
            with open(out, "w") as f:
                f.write(HOT100_FALLBACK)
        return True


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg to make the test card's songs")
class ZunesyncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.card = tempfile.mkdtemp(prefix="zunesync-card-")
        for i, (artist, title, year, *_rest) in enumerate(SONGS):
            d = os.path.join(cls.card, "Music", artist, "Album %d" % i)
            os.makedirs(d)
            f = os.path.join(d, "01 - %s.mp3" % title.replace("/", " "))
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "anullsrc=r=22050:cl=mono", "-t", "2", "-metadata", "artist=" + artist,
                            "-metadata", "title=" + title, "-metadata", "album=Album %d" % i,
                            "-metadata", "date=%d" % (year + 10), "-q:a", "9", f], check=True)
        z = os.path.join(cls.card, "Music", ".zune")
        os.makedirs(z)
        bonu = "Music/Bon Iver/Album 9/01 - Skinny Love.mp3"
        usher = "Music/Usher/Album 8/01 - Yeah!.mp3"
        with open(os.path.join(z, "plays.log"), "w") as f:
            f.write("".join("%d\t%s\n" % (1700000000 + k, bonu) for k in range(7)))
            f.write("1700000100\t%s\n1700000200\t%s\n" % (usher, usher))
        with open(os.path.join(z, "ratings.tsv"), "w") as f:
            f.write("Music/Darude/Album 11/01 - Sandstorm.mp3\t-1\n")
        cls.net = FakeNet()
        cls.lists = zunesync.main([cls.card, "--no-listen", "--size", "10"], net=cls.net)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.card, ignore_errors=True)

    def names(self, pl):
        return [s["title"] for s in self.lists[pl]]

    def test_chill_is_soft_and_not_rnb(self):
        n = self.names("chill")
        self.assertIn("Skinny Love", n)
        self.assertIn("Fade Into You", n)
        self.assertNotIn("Yeah!", n)                    # R&B is not chill
        self.assertNotIn("Hey Ya!", n)

    def test_workout_is_fast_and_builds_up(self):
        w = self.lists["workout"]
        self.assertTrue(w and all(s["bpm"] >= 125 for s in w))
        self.assertEqual([s["bpm"] for s in w], sorted(s["bpm"] for s in w))
        self.assertNotIn("Sandstorm", self.names("workout"))   # disliked on the Pixel 2

    def test_dark_wave_is_the_80s_sound(self):
        n = self.names("dark wave")
        for t in ("Enjoy the Silence", "Blue Monday", "Pain"):
            self.assertIn(t, n)
        self.assertNotIn("Blue (Da Ba Dee)", n)

    def test_nostalgia_is_1998_to_2010_without_jazz_classical_instrumental(self):
        ys = {s["title"]: s["year"] for s in self.lists["nostalgia"]}
        self.assertIn("Hey Ya!", ys)
        self.assertIn("Blue (Da Ba Dee)", ys)
        for t in ("Don't Know Why", "Intro", "Cello Suite No. 1", "Enjoy the Silence"):
            self.assertNotIn(t, ys)
        self.assertTrue(all(1998 <= y <= 2010 for y in ys.values()))

    def test_year_is_the_first_release_not_the_compilation(self):
        s = next(s for s in self.lists["nostalgia"] if s["title"] == "Hey Ya!")
        self.assertEqual(s["year"], 2003)

    def test_jazzy(self):
        n = self.names("jazzy")
        self.assertIn("So What", n)
        self.assertIn("Don't Know Why", n)
        self.assertNotIn("Hey Ya!", n)

    def test_party_is_europop(self):
        n = self.names("party")
        self.assertIn("Blue (Da Ba Dee)", n)
        self.assertIn("We Like to Party!", n)
        self.assertNotIn("So What", n)

    def test_crowd_pleaser_is_billboard_top_50(self):
        n = self.names("crowd pleaser")
        for t in ("Hey Ya!", "Yeah!", "Blue (Da Ba Dee)", "We Like to Party!", "Enjoy the Silence"):
            self.assertIn(t, n)
        self.assertNotIn("Basement Demo", n)
        self.assertTrue(all(s["peak"] <= 50 for s in self.lists["crowd pleaser"]))

    def test_heavy_rotation_is_most_played(self):
        n = self.names("heavy rotation")
        self.assertEqual(n[0], "Skinny Love")
        self.assertIn("Yeah!", n)

    def test_discover_is_unplayed_and_unknown(self):
        n = self.names("discover")
        self.assertIn("Basement Demo", n)
        self.assertNotIn("Skinny Love", n)

    def test_files_written(self):
        p = os.path.join(self.card, "Playlists")
        for name in ("chill", "dark wave", "crowd pleaser"):
            self.assertTrue(os.path.exists(os.path.join(p, name + ".m3u8")))
            self.assertTrue(os.path.exists(os.path.join(p, ".media", name + ".jpg")))
        with open(os.path.join(p, "chill.m3u8")) as f:
            body = f.read()
        self.assertIn(zunesync.MARK, body)
        self.assertIn("../Music/Bon Iver/Album 9/01 - Skinny Love.mp3", body)
        with open(os.path.join(self.card, "Music", ".zune", "library.tsv")) as f:
            rows = [l.split("\t") for l in f.read().splitlines()[1:]]
        row = next(r for r in rows if r[1] == "Hey Ya!")
        self.assertEqual(row[5], "2003")               # the year, from MusicBrainz
        self.assertEqual(row[8], "159")                # the tempo, from Deezer
        self.assertIn("hip hop", row[9])

    def test_rerun_uses_the_cache(self):
        n0 = len(self.net.calls)
        zunesync.main([self.card, "--no-listen", "--size", "10"], net=self.net)
        mb = [u for u in self.net.calls[n0:] if "musicbrainz" in u]
        self.assertEqual(mb, [])

    def test_own_playlist_is_left_alone(self):
        p = os.path.join(self.card, "Playlists", "party.m3u8")
        with open(p, "w") as f:
            f.write("#EXTM3U\n../Music/Miles Davis/Album 5/01 - So What.mp3\n")
        zunesync.main([self.card, "--no-listen", "--size", "10", "--only", "party"], net=self.net)
        with open(p) as f:
            self.assertNotIn(zunesync.MARK, f.read())


class RulesTest(unittest.TestCase):
    """The small parts, without a card or the web."""

    def test_names_in_any_script_are_names(self):
        self.assertEqual(zunesync.fold("Кино"), "кино")
        self.assertNotEqual(zunesync.fold("宇多田ヒカル"), "")
        self.assertNotEqual(zunesync.fold("Кино"), zunesync.fold("宇多田ヒカル"))
        self.assertEqual(zunesync.fold("Beyoncé & Jay-Z"), "beyonce and jay z")

    def test_every_rnb_spelling_is_one_tag(self):
        keys = {zunesync.tag_key(t) for t in ("R&B", "R & B", "RnB", "Rhythm & Blues")}
        self.assertEqual(keys, {"rnb"})
        self.assertEqual(zunesync.tag_key("Contemporary R&B"), "contemporaryrnb")
        self.assertEqual(zunesync.tag_key("Drum & Bass"), "drumandbass")

    def test_a_tag_counts_once_and_whole(self):
        # modern synth-pop alone is not dark wave; it needs the 80s or a dark tag
        self.assertLess(zunesync.has({"synthpop"}, zunesync.DARKWAVE), 2.5)
        self.assertEqual(zunesync.has({"newjackswing"}, zunesync.JAZZ), 0)
        self.assertGreaterEqual(zunesync.has({"smoothjazz"}, zunesync.JAZZ), 1.5)
        self.assertLess(zunesync.has({"dancepop", "electropop"}, zunesync.EURO), 2.5)
        self.assertFalse(zunesync.any_in({"chamberpop"}, zunesync.NOT_NOSTALGIA))
        self.assertFalse(zunesync.any_in({"newromantic"}, zunesync.NOT_NOSTALGIA))
        self.assertTrue(zunesync.any_in({"neoclassical"}, zunesync.NOT_NOSTALGIA))

    def test_a_mood_that_says_not_is_no_mood(self):
        self.assertEqual(zunesync.mood_tag("Relaxed"), "chill")
        self.assertEqual(zunesync.mood_tag("not relaxed"), "")
        self.assertEqual(zunesync.mood_tag(""), "")


class CardFilesTest(unittest.TestCase):
    def setUp(self):
        self.card = tempfile.mkdtemp(prefix="zunesync-files-")
        os.makedirs(os.path.join(self.card, "Music", ".zune"))
        os.makedirs(os.path.join(self.card, "Playlists"))

    def tearDown(self):
        shutil.rmtree(self.card, ignore_errors=True)

    def write(self, rel, data, mode="w"):
        path = os.path.join(self.card, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode) as f:
            f.write(data)
        return path

    def test_device_files_with_bad_lines(self):
        self.write("Music/.zune/plays.log", "\ufeff1700000000\ta.mp3\n\x00\x00\nnot-a-time\tb.mp3\n")
        self.write("Music/.zune/ratings.tsv", "x.mp3\tbad\nMusic/d.mp3\t-1\nMusic/old.mp3\t1\n")
        self.write("Playlists/liked songs.m3u8", "#EXTM3U\n# kept by the Pixel 2\n../Music/l.mp3\n")
        plays, rating = zunesync.read_device(self.card)
        self.assertEqual(plays, {"a.mp3": 1, "b.mp3": 1})
        self.assertEqual(rating, {"Music/d.mp3": -1, "Music/old.mp3": 1, "Music/l.mp3": 1})

    def test_playlist_lines_stay_lines(self):
        song = {"secs": 10, "title": "Two\nLines", "artist": "Tab\tbed", "rel": "Music/a.mp3"}
        self.assertTrue(zunesync.write_playlist(self.card, "chill", [song], False))
        with open(os.path.join(self.card, "Playlists", "chill.m3u8"), encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[2:], ["#EXTINF:10,Two Lines - Tab bed", "../Music/a.mp3"])
        self.assertEqual([f for f in os.listdir(os.path.join(self.card, "Playlists"))
                          if f.endswith(".new")], [])

    def test_fix_playlists_keeps_the_encoding_and_finds_nfd_names(self):
        self.write("Music/Beyoncé/Album/01 Café.mp3", "")
        nfd = unicodedata.normalize("NFD", "C:\\Users\\me\\Music\\Beyoncé\\Album\\01 Café.mp3")
        p = self.write("Playlists/mine.m3u", ("#EXTM3U\n# Beyoncé\n" + nfd + "\n").encode("utf-8"), "wb")
        zunesync.fix_playlists(self.card, False)
        with open(p, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("../Music/Beyoncé/Album/01 Café.mp3", text)
        self.assertTrue(os.path.exists(p + ".bak"))
        p2 = self.write("Playlists/old.m3u", "#EXTM3U\n# Beyonc\xe9\nD:\\x\\01 Café.mp3\n".encode("cp1252"), "wb")
        zunesync.fix_playlists(self.card, False)
        with open(p2, encoding="utf-8") as f:                 # UTF-8 now, for the device
            text = f.read()
        self.assertIn("# Beyoncé", text)                              # read right, not mangled
        self.assertIn("../Music/Beyoncé/Album/01 Café.mp3", text)


class NetTest(unittest.TestCase):
    def test_a_broken_response_is_a_miss_not_a_crash(self):
        net = zunesync.Net()
        with mock.patch("urllib.request.urlopen", side_effect=http.client.IncompleteRead(b"")), \
             mock.patch("time.sleep"):
            self.assertIsNone(net.json("https://example.invalid/x"))
        self.assertEqual(sum(net.failures.values()), 1)


if __name__ == "__main__":
    unittest.main()
