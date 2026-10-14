"""Whether two names are the same thing: strictly, then less so.

Art is looked up by name, and names drift - "The Bends" and "Bends (Collector's
Edition)", "Pokemon Red.gb" and "Pokemon - Red Version (USA, Europe)",
"Legend of Zelda, The" and "The Legend of Zelda". `plain` is the strict key:
case, accents and punctuation set aside, nothing else. `loose` drops what
editions add (bracketed words, " - 2011 Remaster", "feat.", "Disc 2", a
leading or trailing "the") and reads II as 2, for the broader search.
`similar` scores a name found against the one wanted, 0 to 1.
"""
import difflib
import re
import unicodedata

ROMAN = {"ii": "2", "iii": "3", "iv": "4", "vi": "6", "vii": "7", "viii": "8", "ix": "9"}
_BRACKETS = re.compile(r"[(\[{][^)\]}]*[)\]}]")
_DASH_EDITION = re.compile(r"\s+-\s+[^-]*\b(remaster\w*|deluxe|edition|version|anniversary|expanded|"
                           r"bonus|reissue|mono|stereo|explicit|live|mix)\b.*$", re.I)
_FEAT = re.compile(r"\s(feat\.?|ft\.|featuring)\s.*$", re.I)
_DISC = re.compile(r"\b(disc|disk|cd)\s*\d+\b", re.I)


def plain(s):
    """Lowercase words and digits only: "Link's Awakening DX!" is
    "links awakening dx", "Pokémon" is "pokemon", "&" is "and"."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("&", " and ").replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^0-9a-z]+", " ", s).split())


def loose(s, music=True):
    """The broad key. `music`: also drop what a release adds after a dash
    ("Abbey Road - 2019 Mix"), "feat." and "Disc 2" - not for a game, whose
    "Pokemon - Red Version" is its name."""
    s = _BRACKETS.sub(" ", (s or "").replace("_", " "))
    if music:
        s = _DASH_EDITION.sub("", s)
        s = _FEAT.sub("", s)
        s = _DISC.sub(" ", s)
    words = [ROMAN.get(w, w) for w in plain(s).split()]
    # "The Legend of Zelda" and "Legend of Zelda, The" alike.
    rest = [w for w in words if w != "the"]
    return " ".join(rest or words)


def similar(want, got):
    """How like `want` a name found is, both loose keys, 0 to 1: 1 the same,
    high when every word wanted is in it ("pokemon red" in "pokemon red
    version"), else how alike the letters are; 0 when the numbers say it is
    another one. One way: "tetris plus" is not found in "tetris", which is
    another game."""
    if not want or not got:
        return 0.0
    if want == got:
        return 1.0
    tw, tg = set(want.split()), set(got.split())
    # Numbers are which one: "Super Mario Land 2" is not "Super Mario Land",
    # nor "Tetris" "Tetris 2", nor Vol. 2 Vol. 1. Every number wanted must be
    # there, and one more only after a number ("2 - 6 Golden Coins").
    # A year is when, not which ("OK Computer OKNOTOK 1997 2017").
    nw, ng = ({w for w in t if w.isdigit() and not (len(w) == 4 and w[:2] in ("19", "20"))}
              for t in (tw, tg))
    if not nw <= ng or (ng - nw and not nw):
        return 0.0
    score = difflib.SequenceMatcher(None, want, got).ratio()
    if tw <= tg:
        score = max(score, 0.6 + 0.4 * len(tw) / len(tg))
    return score


def same_artist(want, got):
    """The artist asked for, or near enough: "Beyonce" for "Beyoncé",
    "Daft Punk" for "Daft Punk & Pharrell Williams"."""
    a, b = loose(want), loose(got)
    if not a or not b:
        return False
    ta, tb = set(a.split()), set(b.split())
    if a == b or ta <= tb or tb <= ta:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85
