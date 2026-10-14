"""Art lookups against the real services, to see what they answer.

Not a unit test - it needs the internet and the services' good mood - so CI
runs it as information only:  python manager/tests/live_art.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gamezune import albumart, card as C, games  # noqa: E402

ALBUMS = [  # artist, album, a song on it - as a card might name them
    ("Radiohead", "The Bends"),
    ("Daft Punk", "Discovery"),
    ("Beyonce", "Lemonade (Deluxe Edition)"),
    ("The Beatles", "Abbey Road - 2019 Mix"),
    ("AC_DC", "Back In Black"),
    ("Fleetwood Mac", "Rumours [Remastered]"),
    ("The Weeknd", "Unknown Album", "Blinding Lights"),
    ("Taylor Swift", "folklore"),
    ("Various Artists", "Guardians of the Galaxy Awesome Mix Vol. 1"),
]
ROMS = [("Game Boy", "Pokemon Red.gb"), ("Game Boy", "Super Mario Land 2.gb"),
        ("Game Boy", "Tetris (World).gb"), ("Game Boy", "Kirby Dream Land.gb"),
        ("Game Boy Color", "Zelda Link's Awakening DX.gbc"), ("Game Boy Color", "Pokemon Yellow.gbc"),
        ("Game Boy Advance", "Metroid Fusion.gba"), ("Game Boy Advance", "pokemon_emerald.gba")]


def main():
    found = 0
    f = albumart.Finder()
    for a in ALBUMS:
        url, how = f.find(a[0], a[1], a[2:])
        ok = bool(f.picture(url))
        found += ok
        print("album  %-12s %-45s %s" % (how if ok else "NOT FOUND", "%s - %s" % (a[1], a[0]), url or ""))
    root = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(root, "TortOS"))
        card = C.Card(root)
        for sysname, rom in ROMS:
            how = games.fetch_art(card, games.System(sysname, sysname, ()), rom)
            found += bool(how)
            print("game   %-12s %s / %s" % (how or "NOT FOUND", sysname, rom))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("%d of %d found" % (found, len(ALBUMS) + len(ROMS)))


if __name__ == "__main__":
    main()
