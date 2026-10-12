# Game Zune

Turning a **GKD Pixel 2** into an offline Game Boy / Game Boy Color / Game Boy Advance
player and music player, with box art, album art, and a Zune-style interface.

> Status: setup guide. A Zune-style front end/theme is the planned next step — see
> [The Zune look](#the-zune-look).

---

## The hardware, briefly

| | GKD Pixel 2 |
|---|---|
| SoC | Rockchip RK3326S (4× Cortex-A35), 1 GB RAM |
| Screen | 2.4" IPS, 640×480 (4:3) |
| Connectivity | **None** — no Wi-Fi, no Bluetooth. USB-C only. |
| Storage | microSD (the OS boots from the card) |

No Wi-Fi matters for two things in this project:

1. Everything runs offline (good — that's what you want).
2. **Artwork can't be downloaded on the device.** You either prepare art on a computer
   and copy it over, or use a firmware that fetches art *through* your computer over USB.

## Which firmware?

There is no off-the-shelf Zune UI for this handheld. Your choices are:

| Firmware | GB/GBC/GBA | Music player w/ album art | Box art | Zune look? |
|---|---|---|---|---|
| **[TortOS](https://github.com/ericreinsmidt/TortOS)** (recommended) | Yes (mGBA) | **Yes** (Muse: Artist → Album browsing, covers) | Yes, fetched via USB | No — but it's the closest *functionally* |
| [ROCKNIX](https://github.com/ROCKNIX/distribution/releases) | Yes | Only via mpv (plays files, no album library) | Yes (EmulationStation, art scraped on PC) | Possible with a custom ES theme (games only) |
| [Knulli](https://github.com/knulli-cfw/knulli-linux/releases) | Yes | Background music only | Yes (EmulationStation) | Possible with a custom ES theme (games only) |
| Stock (IUX / GMenu2X) | Yes | Basic | Partial | No |

**Recommendation:** use **TortOS**. It's the only option that does *both* halves of what
you want — a real music library with album art and a game shelf with box art — fully
offline, on the Pixel 2, today. It also hides any console with no games in it, so if you
only add GB/GBC/GBA it effectively *becomes* a GB/GBC/GBA + music machine.

---

## Setup with TortOS

### 1. What you need

- A good microSD card (SanDisk/Samsung, 64 GB+ if you have a big music library)
- A computer (Windows 11, macOS, or Linux) and a USB-C **data** cable
- [Raspberry Pi Imager](https://www.raspberrypi.com/software/) or balenaEtcher
- *Optional:* [MusicBrainz Picard](https://picard.musicbrainz.org/) to clean up music tags and embed cover art

### 2. Flash the card

1. Download the latest `TortOS-vX.Y.Z-pixel2.img.xz` from the
   [TortOS releases page](https://github.com/ericreinsmidt/TortOS/releases)
   (Pixel 2 images exist from v1.3.0 onward; check the file against `SHA256SUMS`).
2. Write it to the microSD card with Raspberry Pi Imager
   (*Choose OS → Use custom* → pick the `.img.xz`). **This erases the card.**
3. Put the card in the Pixel 2 and power on. First boot takes longer — it expands the
   storage area for your games, music, and saves.
4. Set the clock: **MENU → Date & Time** (no network, so it can't sync itself).

The card shows up on a computer as a drive named **`TORTOS`**.

### 3. Card layout

Only create the folders you need — empty consoles are hidden from the shelf.

```
TORTOS/
├── Roms/
│   ├── Game Boy/
│   │   ├── Tetris.gb
│   │   └── .media/
│   │       └── Tetris.png          ← box art, same name as the ROM
│   ├── Game Boy Color/
│   │   ├── Pokemon Crystal.gbc
│   │   └── .media/Pokemon Crystal.png
│   └── Game Boy Advance/
│       ├── Metroid Fusion.gba
│       └── .media/Metroid Fusion.png
├── Bios/
│   └── gba_bios.bin                ← optional (GBA runs without it; adds the boot logo)
├── Music/
│   └── Artist/
│       └── Album/
│           ├── 01 - Track.flac
│           └── cover.jpg           ← optional, if covers aren't embedded
└── Saves/                          ← created/used by TortOS
```

Notes:

- **Games:** `.gb`, `.gbc`, `.gba` (zipped ROMs are generally fine too). All three run on mGBA.
- **Music formats:** MP3, M4A/AAC, FLAC, Ogg, Opus, WAV.
- **Music organization:** `Music/Artist/Album/track`. Loose album folders get moved under
  their artist based on tags, and loose songs go to `Music/Singles/` — so good tags matter.

### 4. Get the artwork (box art + album art)

**Easiest — let TortOS fetch it through your computer:**

1. Plug the Pixel 2 into your computer with the USB-C data cable.
2. On the Pixel 2: **MENU → Down To The Wire**. It shows a PIN.
3. On the computer, open **http://10.42.0.1** in a browser and enter the PIN.
4. From this page you can also drag games, music, and saves onto the device.
5. Click **Get Box Art and Album Covers**. Box art comes from the libretro thumbnail
   collection, album covers from MusicBrainz's Cover Art Archive. Both are saved to the card.

Box art is matched by **ROM file name**, so name ROMs the "No-Intro" way
(e.g. `Pokemon - Crystal Version (USA, Europe).gbc`) for the best hit rate.

**Manual / for anything it misses:**

- **Box art:** put a PNG named exactly like the ROM (minus extension) in
  `Roms/<console>/.media/`. ~512 px on the long side is plenty. You can also press **X**
  on a game to replace its cover. Good sources: the
  [libretro-thumbnails](https://github.com/libretro-thumbnails) repos
  (`Nintendo_-_Game_Boy`, `Nintendo_-_Game_Boy_Color`, `Nintendo_-_Game_Boy_Advance`,
  folder `Named_Boxarts`).
- **Album art:** either embed it in the files (Picard: *Options → Cover Art* → enable
  "Embed cover images into tags") or drop a picture (e.g. `cover.jpg`) in the album folder.
  500–600 px square is plenty for a 640×480 screen and keeps the player snappy.

### 5. Daily use

- **SELECT** opens the music player (Muse) from anywhere; music keeps playing when you
  leave it, so you can browse while listening.
- Muse has a lock-screen mode that turns the display off while music plays (saves battery).
- Games autosave and resume where you left off. **Y** favorites a game.
- Shelf sort: name, play time, last played, recently added.
- Updates: use the TortOS Installer → **Update** to keep games/music/saves.
  Re-flashing the image by hand erases the card.

---

## The Zune look

None of the available firmwares ship a Zune-style UI, so this part has to be built.
There are two realistic routes, and this repo is where that work would live:

### Option A — Custom EmulationStation theme on ROCKNIX/Knulli

ROCKNIX (which officially supports the Pixel 2 since its 20260801 release) and Knulli both
use EmulationStation, which is fully themeable with XML + images. A Zune HD–style theme is
very doable:

- Huge lowercase pivot headers (`games`, `game boy`, `game boy advance`) that slide horizontally
- Thin Segoe-like type (use an open font like **Selawik** or **Open Sans Light** — Segoe UI itself isn't redistributable)
- Black background, accent color (Zune magenta/orange), album-grid style box art

**Limitation:** ES is a game launcher. Music would only be reachable as a "system" that
hands files to mpv, not as an Artist → Album library with covers. So you'd get a Zune
look for games, but a weaker music experience than TortOS.

Games setup on ROCKNIX for reference: ROMs in `roms/gb`, `roms/gbc`, `roms/gba`;
BIOS in `roms/bios/`; themes go in `/storage/.config/emulationstation/themes`. Since the Pixel 2 can't scrape, scrape on a
PC with [Skraper](https://www.skraper.net/) (output: EmulationStation, `gamelist.xml` + images) and copy the
result to the card.

### Option B — Dedicated Zune-style front end (the full vision)

A small custom launcher (e.g. LÖVE2D or SDL2) running on ROCKNIX that replaces
EmulationStation and shows a Zune HD–style hub:

```
 music   games   settings
 ─────
 artists  albums  songs  now playing
```

- **music:** Artist → Album grid with album art, now-playing screen, playback via mpv
  (already included in ROCKNIX) in the background
- **games:** GB / GBC / GBA pivots with box-art grids, launching RetroArch (mGBA / Gambatte cores)
- Art read from the same folder conventions as above, so art prepared on a PC just works

This gets the exact look *and* a proper music library, but it's a real software project
that needs testing on the device.

---

## Sources

- TortOS — <https://github.com/ericreinsmidt/TortOS> (README and release notes)
- ROCKNIX releases (Pixel 2 support) — <https://github.com/ROCKNIX/distribution/releases>
- Knulli releases (Pixel 2 image) — <https://github.com/knulli-cfw/knulli-linux/releases>
- Pixel 2 specs — <https://retrocatalog.com/retro-handhelds/gkd-pixel-2>
- ROGUE OS (alternate Pixel 2 CFW) — <https://github.com/Ninoh-FOX/PIXEL2_system_mods>
