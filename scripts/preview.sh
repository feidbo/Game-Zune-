#!/usr/bin/env bash
# Render the Zune theme on your computer, from a demo card, into
# docs/screenshots/. The desktop build draws exactly what the handheld draws,
# at the launcher's 1024x768 (the Pixel 2 shows it at 640x480).
#
#   scripts/preview.sh              the demo card
#   CARD=/path/to/TORTOS scripts/preview.sh   your own card's games and music
#
# Needs: git make gcc pkg-config, SDL2 + SDL2_image + SDL2_ttf dev packages,
# ImageMagick and ffmpeg (for the demo card), and xvfb-run on a machine with
# no display.
#   Debian/Ubuntu: apt install build-essential pkg-config libsdl2-dev
#                  libsdl2-image-dev libsdl2-ttf-dev imagemagick ffmpeg xvfb
set -euo pipefail
. "$(dirname "$0")/common.sh"
need git make cc pkg-config

T=$(tortos_tree) || exit 1
echo "build: desktop preview"
make -C "$T" -f mk/native.mk DEVICE=pixel2 > "$WORK/native.log" 2>&1 ||
	{ grep error "$WORK/native.log" >&2 || true; echo "build failed: see $WORK/native.log" >&2; exit 1; }

demo_card() {
	local c=$1
	need convert ffmpeg
	rm -rf "$c"
	mkdir -p "$c/Roms" "$c/Music" "$c/.userdata/pixel2" "$c/.userdata/shared"
	game() { # folder file color label
		local d="$c/Roms/$1"
		mkdir -p "$d/.media"
		head -c 4096 /dev/urandom > "$d/$2"
		convert -size 360x360 "gradient:$3-#101018" -gravity center -fill white \
		        -pointsize 34 -annotate 0 "$4" "$d/.media/${2%.*}.png"
	}
	game "Game Boy" "Tetris (World).gb" "#7e9b47" "TETRIS"
	game "Game Boy" "Kirby's Dream Land (USA, Europe).gb" "#e88aa8" "KIRBY"
	game "Game Boy" "Super Mario Land (World).gb" "#d33" "MARIO LAND"
	game "Game Boy Color" "Pokemon - Crystal Version (USA, Europe).gbc" "#3aa0c8" "CRYSTAL"
	game "Game Boy Color" "Link's Awakening DX (USA, Europe).gbc" "#3a8a3a" "ZELDA DX"
	game "Game Boy Color" "Wario Land 3 (World).gbc" "#c8a03a" "WARIO 3"
	game "Game Boy Advance" "Metroid Fusion (USA).gba" "#c84a2a" "FUSION"
	game "Game Boy Advance" "Advance Wars (USA).gba" "#2a5ac8" "ADV WARS"
	game "Game Boy Advance" "Golden Sun (USA).gba" "#c8a52a" "GOLDEN SUN"
	game "Game Boy Advance" "Mother 3 (Japan).gba" "#8a3ac8" "MOTHER 3"
	game "Game Boy Advance" "Fire Emblem (USA).gba" "#a02828" "FIRE EMBLEM"
	game "Game Boy Advance" "Minish Cap (USA).gba" "#2a9a5a" "MINISH CAP"
	album() { # artist album color tracks
		local d="$c/Music/$1/$2" i
		mkdir -p "$d"
		convert -size 500x500 "plasma:$3-#202030" -blur 0x6 -gravity south -fill white \
		        -pointsize 40 -annotate +0+30 "$2" "$d/cover.jpg"
		for i in $(seq 1 "$4"); do
			ffmpeg -loglevel error -y -f lavfi -i "sine=frequency=$((200 + i * 40)):duration=2" \
			       -metadata artist="$1" -metadata album_artist="$1" -metadata album="$2" \
			       -metadata title="Track $i" -metadata track="$i" -q:a 9 \
			       "$d/$(printf %02d "$i") - Track $i.mp3"
		done
	}
	album "Daft Punk" "Discovery" "#d04080" 4
	album "Radiohead" "In Rainbows" "#e05020" 4
	album "Boards of Canada" "Music Has the Right" "#40a0a0" 3
	album "The Postal Service" "Give Up" "#5070e0" 3
	album "Daft Punk" "Random Access Memories" "#c0a060" 3
	# Two playlists as scripts/zunesync.py writes them (its MARK line, so a
	# run of it on the demo card replaces them), with covers.
	mkdir -p "$c/Playlists/.media"
	printf '#EXTM3U\n# made by Game Zune zunesync - rerunning it replaces this file\n../Music/Boards of Canada/Music Has the Right/01 - Track 1.mp3\n../Music/Radiohead/In Rainbows/02 - Track 2.mp3\n../Music/The Postal Service/Give Up/01 - Track 1.mp3\n' \
		> "$c/Playlists/chill.m3u8"
	printf '#EXTM3U\n# made by Game Zune zunesync - rerunning it replaces this file\n../Music/Daft Punk/Discovery/01 - Track 1.mp3\n../Music/Daft Punk/Discovery/02 - Track 2.mp3\n../Music/Radiohead/In Rainbows/01 - Track 1.mp3\n../Music/Daft Punk/Random Access Memories/03 - Track 3.mp3\n' \
		> "$c/Playlists/party.m3u8"
	convert -size 500x500 xc:"#40a0a8" -fill white -pointsize 110 -gravity southwest \
	        -annotate +20+20 chill "$c/Playlists/.media/chill.jpg"
	convert -size 500x500 xc:"#ff6020" -fill white -pointsize 110 -gravity southwest \
	        -annotate +20+20 party "$c/Playlists/.media/party.jpg"
	# What scripts/zunesync.py would write: titles, genres, years, lengths,
	# and a few plays and ratings as the Pixel 2 would have logged them.
	python3 - "$c" <<'PY'
import os, sys, time
card = sys.argv[1]
info = {"Daft Punk": ("Electronic", {"Discovery": 2001, "Random Access Memories": 2013}),
        "Radiohead": ("Alternative Rock", {"In Rainbows": 2007}),
        "Boards of Canada": ("Electronic", {"Music Has the Right": 1998}),
        "The Postal Service": ("Indie Pop", {"Give Up": 2003})}
titles = {"Discovery": ["One More Time", "Aerodynamic", "Digital Love", "Harder, Better, Faster, Stronger"],
          "Random Access Memories": ["Give Life Back to Music", "The Game of Love", "Giorgio by Moroder"],
          "In Rainbows": ["15 Step", "Bodysnatchers", "Nude", "Weird Fishes/Arpeggi"],
          "Music Has the Right": ["Wildlife Analysis", "An Eagle in Your Mind", "The Color of the Fire"],
          "Give Up": ["The District Sleeps Alone Tonight", "Such Great Heights", "Sleeping In"]}
rows, paths = ["#zune-index 1"], []
for artist, (genre, albums) in info.items():
    for album, year in albums.items():
        d = os.path.join(card, "Music", artist, album)
        for i, f in enumerate(sorted(x for x in os.listdir(d) if x.endswith(".mp3"))):
            rel = "Music/%s/%s/%s" % (artist, album, f)
            paths.append(rel)
            rows.append("\t".join([rel, titles[album][i], artist, album, genre, str(year),
                                   str(180 + i * 37), str(i + 1), str(100 + i * 7), genre.lower()]))
z = os.path.join(card, "Music", ".zune")
os.makedirs(z, exist_ok=True)
open(os.path.join(z, "library.tsv"), "w").write("\n".join(rows) + "\n")
now = int(time.time())
open(os.path.join(z, "plays.log"), "w").write(
    "".join("%d\t%s\n" % (now - 3600 * k, p) for k, p in enumerate([paths[5], paths[1], paths[9]])))
open(os.path.join(z, "ratings.tsv"), "w").write("%s\t1\n" % paths[2])
PY
}

if [ -n "${CARD:-}" ]; then
	C=$CARD
else
	C=$WORK/demo-card
	[ -f "$C/Music/.zune/library.tsv" ] || demo_card "$C"
fi
# A private TortOS folder to run from. A real card's games and music are
# only read - except that, as on the Pixel 2, the music keeps
# Music/.zune/ratings.tsv and Playlists/liked songs.m3u8 in step when they
# disagree.
RUN=$WORK/preview-root
rm -rf "$RUN" && mkdir -p "$RUN/cards" "$RUN/fonts"
cp "$T/config/systems.cfg" "$T/res/singles.png" "$RUN/"
cp -R "$T/res/cards/." "$RUN/cards/"
cp "$ROOT"/tortos-zune/fonts/*.ttf "$RUN/fonts/"
cp "$ROOT"/tortos-zune/zune-wallpaper.jpg "$RUN/"

OUT=$ROOT/docs/screenshots
mkdir -p "$OUT"
shot() { # name args...
	local name=$1; shift
	local run=()
	command -v xvfb-run > /dev/null && [ -z "${DISPLAY:-}" ] && run=(xvfb-run -a -s "-screen 0 1024x768x24")
	TORTOS_ROOT=$RUN TORTOS_CARD=$C TORTOS_ROMS=$C/Roms \
	TORTOS_USERDATA=$WORK/preview-userdata TORTOS_SHARED=$WORK/preview-shared \
	TORTOS_WEB=$T/res/web TORTOS_FONT=$T/res/fonts/menu.ttf SDL_AUDIODRIVER=dummy \
		${run[@]+"${run[@]}"} "$T/build-native/tortos" --shot "$OUT/$name.png" --theme zune "$@" \
		> "$WORK/shot.log" 2>&1 || true
	# A launcher that crashed or drew nothing says so, rather than leaving an
	# old picture in place.
	grep wrote "$WORK/shot.log" || { echo "shot $name failed:" >&2; tail -5 "$WORK/shot.log" >&2; exit 1; }
}
mkdir -p "$WORK/preview-userdata" "$WORK/preview-shared"
# The top menu, then each side of it.
shot top            --zlevel 0
shot game-boy       --zlevel 1 --sys 0
shot games          --sys 2 --screen games
shot zune           --sys 3 --zmusic zune
# The music collection: the twist row across the top, the list beneath.
shot music-artists  --sys 3 --zmusic artists
shot music-albums   --sys 3 --zmusic albums
shot music-songs    --sys 3 --zmusic songs+letter
shot music-playlists --sys 3 --zmusic playlists
shot music-artist   --sys 3 --zmusic artist:1
shot music-album    --sys 3 --zmusic album:1
shot music-options  --sys 3 --zmusic albums+options
shot now-playing    --nowplaying 2 1 41
shot now-playing-options --nowplaying 2 1 41 --zmusic npoptions
echo "screenshots in $OUT"
