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
    # Harder: short names, other regions' names, subtitles - the looser search.
    ("Game Boy Advance", "Fire Emblem (USA).gba"), ("Game Boy Advance", "Minish Cap (USA).gba"),
    ("Game Boy Color", "Link's Awakening DX (USA, Europe).gbc"),
    ("Game Boy Advance", "Mario & Luigi - Superstar Saga (USA).gba"),
    ("Game Boy Advance", "Pokemon - Fire Red Version (USA).gba"),
    ("Game Boy Advance", "Super Mario Advance 4 - Super Mario Bros. 3 (USA).gba"),
    ("Game Boy", "Donkey Kong Land (USA, Europe).gb"), ("Game Boy Color", "Pokemon Pinball (USA).gbc"),
    ("Game Boy Advance", "Final Fantasy Tactics Advance (USA).gba"),
    ("Game Boy Color", "Mega Man Xtreme (USA, Europe).gbc"),
    ("Game Boy Advance", "Yu-Gi-Oh! - The Eternal Duelist Soul (USA).gba"),
    ("Game Boy Color", "Harry Potter and the Sorcerer's Stone (USA).gbc"),
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
            print("       year=%s genre=%s dev=%s score=%s grade=%s synopsis=%d chars" % (
                r["year"], r["genre"], r["developer"], r["score"] or "-",
                gameinfo.grade(r["score"]) or "-", len(r["synopsis"])))
            print("       fact: %s" % (r["fact"][:150] or "-"))
    print("of %d: %s" % (len(ROMS), ", ".join("%s %d" % kv for kv in counts.items())))


if __name__ == "__main__":
    main()
