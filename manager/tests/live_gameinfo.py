"""Game info against the real Wikipedia and Wikidata, to see what they hold.

Not a unit test - it needs the internet - so CI runs it as information:
python manager/tests/live_gameinfo.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gamezune import gameinfo  # noqa: E402

ROMS = [
    ("Game Boy", "Tetris (World) (Rev 1).gb"), ("Game Boy", "Pokemon - Red Version (USA, Europe) (SGB Enhanced).gb"),
    ("Game Boy", "Kirby's Dream Land (USA, Europe).gb"), ("Game Boy", "Super Mario Land 2 - 6 Golden Coins (USA, Europe).gb"),
    ("Game Boy", "Gargoyle's Quest (USA, Europe).gb"), ("Game Boy", "Mole Mania (USA, Europe) (SGB Enhanced).gb"),
    ("Game Boy", "Pokemon Red.gb"),
    ("Game Boy Color", "Legend of Zelda, The - Link's Awakening DX (USA, Europe) (Rev 2) (SGB Enhanced).gbc"),
    ("Game Boy Color", "Pokemon - Crystal Version (USA, Europe) (Rev 1).gbc"), ("Game Boy Color", "Shantae (USA).gbc"),
    ("Game Boy Color", "Wario Land 3 (World) (En,Ja).gbc"), ("Game Boy Color", "Harvest Moon GBC (USA).gbc"),
    ("Game Boy Color", "Dragon Warrior Monsters (USA, Europe).gbc"),
    ("Game Boy Advance", "Metroid Fusion (USA).gba"), ("Game Boy Advance", "Advance Wars (USA) (Rev 1).gba"),
    ("Game Boy Advance", "Golden Sun (USA, Europe).gba"), ("Game Boy Advance", "Mother 3 (Japan).gba"),
    ("Game Boy Advance", "Castlevania - Aria of Sorrow (USA).gba"), ("Game Boy Advance", "Ninja Five-O (USA).gba"),
    ("Game Boy Advance", "Kuru Kuru Kururin (Europe).gba"),
]


def main():
    w = gameinfo.Wiki()
    counts = dict.fromkeys(("source", "year", "genre", "developer", "score", "synopsis", "fact"), 0)
    for system, rom in ROMS:
        r = gameinfo.lookup(w, system, rom)
        for k in counts:
            counts[k] += bool(r[k])
        print("%-4s %-40s -> %s" % (system.replace("Game Boy", "GB").replace(" Color", "C").replace(" Advance", "A"),
                                    gameinfo.rom_title(rom)[:40], r["source"] or "NOT FOUND"))
        if r["source"]:
            print("       year=%s genre=%s dev=%s score=%s synopsis=%d chars" % (
                r["year"], r["genre"], r["developer"], r["score"] or "-", len(r["synopsis"])))
            print("       fact: %s" % (r["fact"][:150] or "-"))
    print("of %d: %s" % (len(ROMS), ", ".join("%s %d" % kv for kv in counts.items())))


if __name__ == "__main__":
    main()
