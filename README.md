# Game Zune

A **GKD Pixel 2** set up as an offline Game Boy / Game Boy Color / Game Boy Advance
player and music player, with box art, album art, and a **Zune HD interface**.

It is [TortOS](https://github.com/ericreinsmidt/TortOS) (games + music + art, offline)
with a Zune theme added to its launcher.

| Hub | Games | Albums | Now playing |
|---|---|---|---|
| ![hub](docs/screenshots/hub.png) | ![games](docs/screenshots/games.png) | ![albums](docs/screenshots/albums.png) | ![now playing](docs/screenshots/now-playing.png) |

*(Screenshots are from the desktop build of the launcher with a demo card. It draws the
same thing the handheld draws, at 1024×768; the Pixel 2 shows it at 640×480.)*

> **Status:** the Zune theme builds for the Pixel 2 and links against the exact
> libraries in the TortOS 1.6.0 image. It has **not been run on a real Pixel 2 yet**.
> Installing it is reversible in one file copy; see [If something goes wrong](#if-something-goes-wrong).

---

## What you get

- **Hub:** big lowercase words (`game boy`, `game boy color`, `game boy advance`, `music`).
  The art for wherever you are in that shelf shows beside them, and "now playing" sits along the bottom.
- **Game lists:** a huge heading that runs off the screen, with **pivots** for the sort order
  (`name · play time · last played · recently added`). Below them is a list of box art and titles.
  The selected title is in Zune magenta.
- **Music:** the same list for albums, with covers and artists. Pivots switch between artist and album order.
- **Now playing:** the artist's name drifts enormous across the top, like on the Zune HD.
  Below it are the cover, the track, a magenta progress line and what plays next.
- **Menus** switch to the same typeface, with flat black panels and a magenta accent.
- The font is [Selawik](https://github.com/microsoft/Selawik), Microsoft's open-source
  stand-in for Segoe, the Zune's typeface family.

Everything else is stock TortOS: mGBA for all three Game Boys, the Muse music player,
autosave/resume, favorites, Down To The Wire for files and art over USB.

### Controls on the Zune theme

| Button | Does |
|---|---|
| Up / Down | Move |
| Left / Right | Jump by letter |
| L1 / R1 | Change pivot (sort order) |
| A / B | Open or play / back |
| X / Y | Game details / favorite |
| SELECT | Music (from anywhere) |
| MENU | TortOS menu (UI Theme is in here) |

---

## Setup

### 1. Flash TortOS 1.6.0

1. Download **`TortOS-v1.6.0-pixel2.img.xz`** from the
   [TortOS v1.6.0 release](https://github.com/ericreinsmidt/TortOS/releases/tag/v1.6.0).
2. Write it to a microSD card with [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
   (*Choose OS → Use custom*). This erases the card.
3. Boot the Pixel 2 from it once. The first boot sets up the card. Set the clock in **MENU → Date & Time**.
4. Power off and put the card in your computer. It shows up as **`TORTOS`**.

The Zune build is made for **this exact release**. Its launcher talks to the emulator and
music player beside it, so the versions must match. The install script checks this.

### 2. Install the Zune theme

The ready-built files are in [`dist/TortOS/`](dist/TortOS): the launcher (`tortos.elf`) and its fonts.

**macOS / Linux:**

```sh
scripts/install-to-card.sh /Volumes/TORTOS        # macOS
scripts/install-to-card.sh /media/$USER/TORTOS    # Linux
```

**Windows (or by hand):**

1. On the card, rename `TortOS\tortos.elf` to `tortos.elf.stock`. This is your way back.
2. Copy everything in this repo's `dist\TortOS\` into the card's `TortOS\` folder,
   merging the `fonts` folder.

Eject, put the card in the Pixel 2, power on. A fresh install starts in the Zune theme. If
yours does not, open **MENU → UI Theme → Zune**. *Plain Jane* and *Fancy Pants* are still
there if you want TortOS's own look back.

### 3. Add games, music and art

Card layout (only the folders you use. Empty systems are hidden):

```
TORTOS/
├── Roms/
│   ├── Game Boy/           Tetris (World).gb
│   ├── Game Boy Color/     Pokemon - Crystal Version (USA, Europe).gbc
│   └── Game Boy Advance/   Metroid Fusion (USA).gba
│       └── .media/         Metroid Fusion (USA).png   ← box art, same name as the ROM
├── Bios/gba_bios.bin       ← optional (GBA runs without it)
└── Music/Artist/Album/01 - Track.flac  (+ cover.jpg, or covers embedded in the files)
```

- **Formats:** `.gb .gbc .gba` (zipped is fine). Music: MP3, M4A/AAC, FLAC, Ogg, Opus, WAV.
- **Art without Wi-Fi:** connect the Pixel 2 to your computer by USB and open **MENU → Down To The Wire**.
  Go to **http://10.42.0.1** in your computer's browser and enter the PIN. Press
  **Get Box Art and Album Covers**: box art comes from libretro's thumbnail collection and covers
  from MusicBrainz, saved to the card. The same page lets you drag games and music on.
- Box art is matched by ROM file name, so No-Intro-style names (`Game (USA).gba`) match best.
  Anything it misses: drop a PNG with the ROM's name into `Roms/<system>/.media/`
  (~512 px is plenty). For music, embed covers with [MusicBrainz Picard](https://picard.musicbrainz.org/)
  or put a `cover.jpg` in the album folder.
- Good tags matter: TortOS files albums under their artist from the tags.

---

## If something goes wrong

The launcher is one file on the card, so recovery is easy:

- **Restore stock:** `scripts/install-to-card.sh /path/to/TORTOS --restore`. Or, by hand,
  copy `TortOS/tortos.elf.stock` back over `TortOS/tortos.elf`.
- If the launcher fails to start five times in a row, TortOS powers the device off by
  design. Put the card in your computer and restore as above.
- The log is on the card at `.userdata/pixel2/logs/tortos.log`. It is useful for reporting what happened.

**Updating TortOS:** a newer TortOS image replaces `TortOS/tortos.elf` with its own,
which turns the theme off. To get it back, the patch needs bumping to that release: set the
new version in [`tortos-zune/UPSTREAM`](tortos-zune/UPSTREAM) and rebuild. The patch
touches the launcher only and may apply as is.

---

## Building it yourself

Linux (or WSL). Nothing needs the device:

```sh
# Debian/Ubuntu
sudo apt install git curl xz-utils python3 e2fsprogs make gcc-aarch64-linux-gnu
scripts/build-pixel2.sh      # -> dist/TortOS/
```

The script does four things:

1. Clones TortOS at the pinned release and applies
   [`tortos-zune/patches/0001-zune-theme.patch`](tortos-zune/patches/0001-zune-theme.patch).
2. Takes the SDL libraries out of that release's own Pixel 2 image (hash-checked).
3. Cross-compiles the launcher against them.
4. Puts it in `dist/` with the fonts.

To preview on your computer (also regenerates the screenshots above):

```sh
sudo apt install build-essential pkg-config libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev imagemagick ffmpeg xvfb
scripts/preview.sh                      # demo card
CARD=/media/$USER/TORTOS scripts/preview.sh   # your own games and music (read only)
```

### What the patch changes

- `src/zune.c`, `src/zune.h` (new): the drawing. These are the panorama heading, pivots, art lists,
  the hub's word column and quickplay tiles, and Now Playing.
- `src/main.c`:
  - Hooks the theme into the shelves, the Muse album shelf and Now Playing.
  - Makes the list navigation run top to bottom, with L1/R1 as pivots. The sort-step code now lives in
    one shared function, used by both the menu and the pivots.
  - Adds `--theme`/`--sys` to the screenshot harness.
- `src/ui.c`, `src/ui.h`: switching the menu typeface at runtime, and flat panels.
- `src/cards.h`: *Zune* as a third UI Theme, and the default.
- `src/controls.*`: a Controls page for the Zune layout.

TortOS's own offline checks (`make check`) pass with the patch applied.

---

## Why TortOS (and not plumOS, ROCKNIX, Knulli…)

| | Music library with album art | Box art offline | Games | Zune look possible |
|---|---|---|---|---|
| **TortOS** | Yes (Muse) | Yes, via USB | mGBA | **Yes — this repo** |
| plumOS | No music player found | Scrape on PC | Gambatte, gpSP | Games only (ES theme) |
| ROCKNIX / Knulli | Plays files through mpv / background music only | Scrape on PC | Yes | Games only (ES theme) |

The Pixel 2 has no Wi-Fi or Bluetooth. TortOS is the one that already handles art for that
case, and the one with a real music library, so it is the base.

## Licenses

- This repo: GPL-3.0 ([LICENSE](LICENSE)).
- The patch and `dist/TortOS/tortos.elf` are TortOS modifications. TortOS is MIT,
  © Eric Reinsmidt, and the patch is offered under the same MIT terms so it can go upstream.
- Selawik: SIL Open Font License 1.1, © Microsoft ([fonts/OFL-Selawik.txt](tortos-zune/fonts/OFL-Selawik.txt)).
- "Zune" is a Microsoft trademark. This is an unaffiliated, fan-made look-alike theme.

## Sources

- TortOS: <https://github.com/ericreinsmidt/TortOS>
- plumOS for Pixel 2: <https://github.com/game-de-it/plumOS-pixel2>
- ROCKNIX releases: <https://github.com/ROCKNIX/distribution/releases> · Knulli: <https://github.com/knulli-cfw/knulli-linux/releases>
- Pixel 2 specs: <https://retrocatalog.com/retro-handhelds/gkd-pixel-2>
