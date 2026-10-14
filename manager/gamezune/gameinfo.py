"""What a game is: year, genre, studio, critics' score, synopsis, a fun fact.

The Pixel 2 has no Wi-Fi, so the computer looks it up and leaves it on the
card in Roms/.zune/games.tsv, where the Zune theme's games list and game page
read it. Everything comes from Wikipedia and Wikidata - free, no key:

  which game   Wikipedia's search for the title and the system, then the
               Wikidata item of each page found: it has to be on this Game
               Boy (or the other one, for a cartridge that plays on both) and
               be named like the ROM (gamezune/match.py).
  year         Wikidata's publication dates, the earliest.
  genre        Wikidata's genres, "role-playing video game" as "role-playing".
  studio       Wikidata's developer; the publisher beside it.
  score        the article's own "Video game reviews" table, which is where
               Wikipedia keeps Metacritic's number - this system's where it
               names systems. Metacritic first; GameRankings, then the
               critics the table lists, when Metacritic never scored it,
               which is most Game Boy and Game Boy Color games (Metacritic's
               game scores begin around 2001). Wikidata's review scores when
               the article has no table.
  synopsis     the article's opening paragraphs.
  fun fact     one sentence from its development, release or legacy, chosen
               for the words trivia is made of ("originally", "named after",
               "million") and left out when nothing reads like one.
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

from .match import loose, similar

UA = "GameZune/1.0 (https://github.com/feidbo/Game-Zune-; card manager for a Game Boy player)"
WP = "https://en.wikipedia.org/w/api.php"
WD = "https://www.wikidata.org/w/api.php"
TSV = ("Roms", ".zune", "games.tsv")
COLUMNS = ("folder", "file", "title", "year", "genre", "developer", "publisher", "score",
           "synopsis", "fact", "source")

# Wikidata's items for the three, and what Wikipedia's review tables call them.
PLATFORMS = {"Game Boy": "Q186437", "Game Boy Color": "Q203992", "Game Boy Advance": "Q188642"}
ABBREV = {"Game Boy": ("GB",), "Game Boy Color": ("GBC",), "Game Boy Advance": ("GBA",)}
SIBLING = {"Game Boy": "Game Boy Color", "Game Boy Color": "Game Boy"}
CLOSE = 0.75
# A series or a franchise is not a game: "Pokemon Red.gb" found "Pokemon
# (video game series)" on the live run.
NOT_A_GAME = {"Q7058673", "Q196600", "Q1824797"}     # video game series, media franchise
FIRST_YEAR = {"Game Boy": 1989, "Game Boy Color": 1998, "Game Boy Advance": 2001}
NOISE = {"version", "edition", "game", "video"}

# The review table's critics, by its parameter names, in the order to prefer.
CRITICS = [("MC", "metacritic"), ("GR", "gamerankings"), ("Fam", "famitsu"), ("IGN", "ign"),
           ("GSpot", "gamespot"), ("NP", "nintendo power"), ("EGM", "egm"), ("GI", "game informer"),
           ("AllGame", "allgame"), ("NLife", "nintendo life"), ("GamePro", "gamepro"),
           ("1UP", "1up"), ("Edge", "edge"), ("EuroG", "eurogamer"), ("GameZone", "gamezone")]

# Trivia words weigh more than sales words: a sales figure is the fallback,
# not the first choice (CI's live run picked one for nearly every game).
OUT_OF_TEN = {"IGN", "GSpot", "NLife", "EuroG", "Edge", "GameZone"}   # their scale, when a table leaves it off
FACT_WORDS = {"originally": 5, "named after": 6, "inspired": 5, "working title": 6,
              "easter egg": 6, "secret": 4, "hidden": 3, "cancel": 3, "prototype": 4,
              "unused": 4, "intended": 3, "based on": 3, "guinness": 5, "the first": 3,
              "first ": 1, "only ": 1, "never": 1, "rare": 1, "record": 2, "ported": 1,
              "best-selling": 3, "million": 2, "sold": 1, "remake": 1, "sequel": 1,
              "composer": 2, "voice": 1, "cameo": 4, "reference": 3}
FACT_AVOID = ("praised", "criticized", "criticised", "review", "score", "rated", "metacritic",
              "gamerankings", "aggregat", "citation needed", " felt ", " said", "called it",
              "described", "opined", "\"")
FACT_SECTIONS = ("development", "production", "design", "release", "legacy", "sales",
                 "trivia", "history", "reception", "music", "marketing", "localization")


class Wiki:
    """The two APIs, paced and remembered for one run. `get` is replaceable
    for tests: url -> bytes or None."""

    def __init__(self, get=None, pace=True):
        self.get = get or _get
        self.pace = pace
        self.last = 0.0
        self.cache = {}

    def api(self, base, **params):
        params.update(format="json", formatversion="2")
        url = base + "?" + urllib.parse.urlencode(params)
        if url in self.cache:
            return self.cache[url]
        if self.pace:
            wait = self.last + 0.15 - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
        raw = self.get(url)
        try:
            out = json.loads(raw.decode("utf-8")) if raw else None
        except (ValueError, UnicodeDecodeError):
            out = None
        self.cache[url] = out
        return out

    def search(self, q):
        """[(page title, wikidata id)] in Wikipedia's order."""
        d = self.api(WP, action="query", generator="search", gsrsearch=q, gsrlimit=8,
                     gsrnamespace=0, prop="pageprops", ppprop="wikibase_item")
        pages = ((d or {}).get("query") or {}).get("pages") or []
        pages = sorted(pages, key=lambda p: p.get("index", 99))
        return [(p["title"], (p.get("pageprops") or {}).get("wikibase_item"))
                for p in pages if p.get("title")]

    def entities(self, ids, props="labels|claims|sitelinks"):
        out = {}
        ids = [i for i in ids if i]
        for k in range(0, len(ids), 50):
            d = self.api(WD, action="wbgetentities", ids="|".join(ids[k:k + 50]), props=props,
                         languages="en", sitefilter="enwiki")
            out.update(((d or {}).get("entities") or {}))
        return out

    def labels(self, ids):
        ents = self.entities(sorted(set(ids)), props="labels")
        return {q: ((e.get("labels") or {}).get("en") or {}).get("value", "") for q, e in ents.items()}

    def text(self, title):
        d = self.api(WP, action="query", prop="extracts", explaintext=1, exsectionformat="wiki",
                     titles=title, redirects=1)
        pages = ((d or {}).get("query") or {}).get("pages") or []
        return (pages[0].get("extract") or "") if pages else ""

    def wikitext(self, title):
        d = self.api(WP, action="query", prop="revisions", rvprop="content", rvslots="main",
                     titles=title, redirects=1)
        pages = ((d or {}).get("query") or {}).get("pages") or []
        try:
            return pages[0]["revisions"][0]["slots"]["main"]["content"]
        except (IndexError, KeyError, TypeError):
            return ""


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


# ---- names -------------------------------------------------------------------------

def rom_title(rom):
    """"Legend of Zelda, The - Link's Awakening DX (USA, Europe) (Rev 2).gbc"
    as a search would say it: "The Legend of Zelda Link's Awakening DX"."""
    stem = os.path.splitext(os.path.basename(rom))[0].replace("_", " ")
    stem = re.split(r"\s*[(\[]", stem, 1)[0].strip()
    parts = [p.strip() for p in stem.split(" - ")]
    parts = [("The " + p[:-5]) if p.endswith(", The") else p for p in parts]
    return " ".join(p for p in parts if p)


def _core(s):
    """loose, less the words that only say which release: "Pokemon Red
    Version" is "pokemon red"."""
    words = [w for w in loose(s, music=False).split() if w not in NOISE]
    return " ".join(words)


def _claims(ent, prop):
    return [c for c in (ent.get("claims") or {}).get(prop, [])
            if (c.get("mainsnak") or {}).get("snaktype") == "value"]


def _qids(ent, prop):
    out = []
    for c in _claims(ent, prop):
        v = c["mainsnak"].get("datavalue", {}).get("value")
        if isinstance(v, dict) and v.get("id"):
            out.append(v["id"])
    return out


def find(wiki, system, rom):
    """The game's (Wikipedia title, Wikidata item) or (None, None)."""
    title = rom_title(rom)
    want = _core(title)
    if not want:
        return None, None
    plats = {PLATFORMS[system]: 2}
    if system in SIBLING:
        plats[PLATFORMS[SIBLING[system]]] = 1
    hits = []
    for q in ("%s %s video game" % (title, system), "%s video game" % title):
        hits = [(t, q_) for t, q_ in wiki.search(q) if q_]
        if hits:
            ents = wiki.entities([q_ for _, q_ in hits])
            best, key = None, None
            for rank, (t, qid) in enumerate(hits):
                ent = ents.get(qid) or {}
                if set(_qids(ent, "P31")) & NOT_A_GAME or re.search(r"\b(series|franchise)\b", t, re.I):
                    continue
                on = max([plats.get(p, 0) for p in _qids(ent, "P400")] or [0])
                if not on:
                    continue
                label = ((ent.get("labels") or {}).get("en") or {}).get("value", "")
                page = re.sub(r"\s*\((?:[^)]*video game|[^)]*game)\)$", "", t)
                sc = max(similar(want, _core(label)), similar(want, _core(page)))
                if sc < CLOSE:
                    continue
                k = (round(sc, 2), on, -rank)
                if key is None or k > key:
                    best, key = (t, qid, ent), k
            if best:
                return best[0], best[2]
    return None, None


# ---- the facts ------------------------------------------------------------------------

def _year(ent, system, intro=""):
    """The first release on or after the system's own launch - a later date
    is a re-release (Harvest Moon GB came back as "2012") - else the year
    the article's opening names ("Shantae is a 2002 platform game")."""
    years = []
    for c in _claims(ent, "P577"):
        t = (c["mainsnak"].get("datavalue", {}).get("value") or {}).get("time", "")
        m = re.match(r"[+-]?(\d{4})", t)
        if m:
            years.append(int(m.group(1)))
    # A cartridge that plays on both Game Boys may be the other one's game.
    first = min(FIRST_YEAR.get(system, 1980), FIRST_YEAR.get(SIBLING.get(system, ""), 9999))
    era = [y for y in years if first <= y <= first + 12]
    m = re.search(r"\b((?:19|20)\d\d)\b[^.]{0,60}\b(?:video )?game\b", intro)
    told = int(m.group(1)) if m and first <= int(m.group(1)) <= first + 12 else None
    if era:
        return str(min(era))
    if told:
        return str(told)
    return str(min(years)) if years else ""


def _genre_word(label):
    g = re.sub(r"\s+(video\s+)?game$", "", label.strip(), flags=re.I)
    return g.lower() if g else ""


def _clean_value(v):
    v = re.sub(r"<!--.*?-->", "", v, flags=re.S)
    v = re.sub(r"<ref[^>/]*/>", "", v)
    v = re.sub(r"<ref[^>]*>.*?</ref>", "", v, flags=re.S)
    v = re.sub(r"\{\{\s*(?:rating|star)\s*\|\s*([\d.]+)\s*\|\s*(\d+)[^}]*\}\}", r"\1/\2", v, flags=re.I)
    v = re.sub(r"\{\{[^{}]*\}\}", "", v)
    v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"'''?", "", v)
    return v


def review_table(wikitext, system):
    """{critic: score} from the article's "Video game reviews" table, for
    this system where the table names systems."""
    m = re.search(r"\{\{\s*Video game reviews", wikitext, re.I)
    if not m:
        return {}
    # The template's own braces, nested ones included.
    depth, i = 0, m.start()
    while i < len(wikitext):
        if wikitext.startswith("{{", i):
            depth += 1
            i += 2
        elif wikitext.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                break
        else:
            i += 1
    body = wikitext[m.end():i - 2]
    # Split on the template's own pipes, not those of templates and links in it.
    params, cur, d = [], "", 0
    for ch_i, ch in enumerate(body):
        if body.startswith(("{{", "[["), ch_i):
            d += 1
        elif body.startswith(("}}", "]]"), ch_i):
            d -= 1
        if ch == "|" and d <= 0:
            params.append(cur)
            cur = ""
        else:
            cur += ch
    params.append(cur)
    mine = ABBREV.get(system, ())
    out = {}
    for p in params:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        k = k.strip()
        v = _clean_value(v).strip()
        v = re.sub(r"(\d+(?:\.\d+)?)\s*out of\s*(\d+)", r"\1/\2", v, flags=re.I)
        if not v:
            continue
        # "GBA: 85/100<br />PS2: 80/100" - this system's, or none; a bare
        # value is the game's own.
        parts = re.split(r"<br\s*/?>|\n|;", v)
        tagged = [re.match(r"\s*\(?([A-Za-z0-9 ]+?)\)?\s*:\s*(.+)$", x) for x in parts]
        if any(tagged):
            vals = [t.group(2) for t in tagged if t and t.group(1).strip().upper() in mine]
            if not vals:
                continue
            v = vals[0]
        num = re.search(r"\d+(?:\.\d+)?\s*(?:/\s*\d+|%)?", v)
        if num:
            out[k] = re.sub(r"\s+", "", num.group(0))
    return out


def score_label(table):
    """"metacritic 92", "gamerankings 88%", "famitsu 30/40" - the first of
    CRITICS the table has."""
    for key, name in CRITICS:
        v = table.get(key)
        if not v:
            continue
        if key == "MC":
            v = v.split("/")[0]
        elif key == "GR" and not v.endswith("%"):
            v = v.split("/")[0] + "%"
        elif key == "GR":
            v = "%d%%" % int(float(v[:-1]) + 0.5)
        elif key in OUT_OF_TEN and "/" not in v and not v.endswith("%"):
            v += "/10"     # 88.5 is 89, not round()'s 88
        return "%s %s" % (name, v)
    return ""


def _wikidata_score(wiki, ent, system):
    best = None
    scores = []
    for c in _claims(ent, "P444"):
        v = c["mainsnak"].get("datavalue", {}).get("value")
        q = c.get("qualifiers") or {}
        by = [x.get("datavalue", {}).get("value", {}).get("id") for x in q.get("P447", [])]
        on = [x.get("datavalue", {}).get("value", {}).get("id") for x in q.get("P400", [])]
        if on and PLATFORMS[system] not in on:
            continue
        if isinstance(v, str) and by and by[0]:
            scores.append((by[0], v))
    if not scores:
        return ""
    names = wiki.labels([b for b, _ in scores])
    order = [n for _, n in CRITICS]
    for b, v in sorted(scores, key=lambda s: order.index(names.get(s[0], "").lower())
                       if names.get(s[0], "").lower() in order else 99):
        name = names.get(b, "").lower()
        if name:
            best = "%s %s" % (name, v.split("/")[0] if name == "metacritic" else v.replace(" ", ""))
            break
    return best or ""


def _sections(text):
    """[(heading, body)] of a plain-text extract; the opening is heading ""."""
    out, head, buf = [], "", []
    for line in text.split("\n"):
        m = re.match(r"^(=+)\s*(.*?)\s*=+$", line.strip())
        if m:
            out.append((head, "\n".join(buf).strip()))
            head, buf = m.group(2), []
        else:
            buf.append(line)
    out.append((head, "\n".join(buf).strip()))
    return out


def _sentences(body):
    body = re.sub(r"\s+", " ", body)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", body) if s.strip()]


def synopsis(text, limit=700):
    intro = next((b for h, b in _sections(text) if h == ""), "")
    out = ""
    for s in _sentences(intro):
        if len(out) + len(s) + 1 > limit:
            break
        out = (out + " " + s).strip()
    return out


def fun_fact(text):
    best, score = "", 0
    for head, body in _sections(text):
        if not head or not any(w in head.lower() for w in FACT_SECTIONS):
            continue
        for s in _sentences(body):
            low = s.lower()
            if not 50 <= len(s) <= 230 or any(w in low for w in FACT_AVOID) or s.endswith(":"):
                continue
            sc = sum(w for k, w in FACT_WORDS.items() if k in low)
            if re.search(r"\d", s):
                sc += 1
            if sc > score:
                best, score = s, sc
    return best if score >= 3 else ""


def lookup(wiki, system, rom):
    """{column: value} for one ROM; source "" when nothing was found."""
    row = dict.fromkeys(COLUMNS, "")
    title, ent = find(wiki, system, rom)
    if not ent:
        return row
    row["source"] = title
    row["title"] = ((ent.get("labels") or {}).get("en") or {}).get("value", "") or title
    genres, devs, pubs = _qids(ent, "P136"), _qids(ent, "P178"), _qids(ent, "P123")
    names = wiki.labels(genres + devs + pubs) if genres or devs or pubs else {}
    row["genre"] = ", ".join(dict.fromkeys(g for g in (_genre_word(names.get(q, "")) for q in genres) if g))
    row["developer"] = ", ".join(n for n in (names.get(q, "") for q in devs[:2]) if n)
    row["publisher"] = ", ".join(n for n in (names.get(q, "") for q in pubs[:2]) if n)
    row["score"] = score_label(review_table(wiki.wikitext(title), system)) or \
        _wikidata_score(wiki, ent, system)
    text = wiki.text(title)
    row["year"] = _year(ent, system, next((b for h, b in _sections(text) if h == ""), ""))
    row["synopsis"] = synopsis(text)
    row["fact"] = fun_fact(text)
    return row


# ---- the card's file ------------------------------------------------------------------

def _esc(v):
    return (v or "").replace("\\", "\\\\").replace("\t", " ").replace("\r", "").replace("\n", "\\n")


def _unesc(v):
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) == "n" else m.group(1), v)


def load(card):
    """{(folder, file): row} from the card's games.tsv."""
    out = {}
    try:
        with open(card.path(*TSV), encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                cells = line.rstrip("\n").split("\t")
                if len(cells) < 2:
                    continue
                row = dict(zip(COLUMNS, [_unesc(c) for c in cells] + [""] * len(COLUMNS)))
                out[(row["folder"], row["file"])] = row
    except OSError:
        pass
    return out


def save(card, rows):
    from .playlists import write_atomic
    lines = ["# Game Zune: what each game is, for the Pixel 2's games list and game page."
             " Made by the Game Zune app from Wikipedia and Wikidata (CC BY-SA)."
             " Columns: " + " ".join(COLUMNS)]
    for key in sorted(rows):
        r = rows[key]
        lines.append("\t".join(_esc(r.get(c, "")) for c in COLUMNS))
    write_atomic(card.path(*TSV), "\n".join(lines) + "\n")


def has_info(rows, folder, rom):
    r = rows.get((folder, rom))
    return bool(r and r.get("source"))


def fetch(card, system, roms, wiki=None, progress=None, cancelled=lambda: False):
    """Look the ROMs up and keep what was found in games.tsv. Returns
    (found, missing): lists of ROM names."""
    wiki = wiki or Wiki()
    rows = load(card)
    found, missing = [], []
    for i, rom in enumerate(roms):
        if cancelled():
            break
        if progress:
            progress(i, len(roms), rom_title(rom))
        row = lookup(wiki, system.name, rom)
        row["folder"], row["file"] = system.folder, rom
        if row["source"]:
            found.append(rom)
            rows[(system.folder, rom)] = row
        else:
            missing.append(rom)
            rows.setdefault((system.folder, rom), row)
        if i % 10 == 9:
            save(card, rows)
    save(card, rows)
    if progress:
        progress(len(roms), len(roms), "")
    return found, missing
