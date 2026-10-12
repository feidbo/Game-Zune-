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

T=$(tortos_tree)
echo "build: desktop preview"
make -C "$T" -f mk/native.mk DEVICE=pixel2 > "$WORK/native.log" 2>&1 ||
	{ grep error "$WORK/native.log" >&2; exit 1; }

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
}

if [ -n "${CARD:-}" ]; then
	C=$CARD
else
	C=$WORK/demo-card
	[ -d "$C/Roms" ] || demo_card "$C"
fi
# A private TortOS folder to run from, so a real card is only ever read.
RUN=$WORK/preview-root
rm -rf "$RUN" && mkdir -p "$RUN/cards" "$RUN/fonts"
cp "$T/config/systems.cfg" "$T/res/singles.png" "$RUN/"
cp -R "$T/res/cards/." "$RUN/cards/"
cp "$ROOT"/tortos-zune/fonts/*.ttf "$RUN/fonts/"

OUT=$ROOT/docs/screenshots
mkdir -p "$OUT"
shot() { # name args...
	local name=$1; shift
	local run=()
	command -v xvfb-run > /dev/null && [ -z "${DISPLAY:-}" ] && run=(xvfb-run -a -s "-screen 0 1024x768x24")
	TORTOS_ROOT=$RUN TORTOS_CARD=$C TORTOS_ROMS=$C/Roms \
	TORTOS_USERDATA=$WORK/preview-userdata TORTOS_SHARED=$WORK/preview-shared \
	TORTOS_WEB=$T/res/web TORTOS_FONT=$T/res/fonts/menu.ttf SDL_AUDIODRIVER=dummy \
		"${run[@]}" "$T/build-native/tortos" --shot "$OUT/$name.png" --theme zune "$@" \
		2>&1 | grep wrote || true
}
mkdir -p "$WORK/preview-userdata" "$WORK/preview-shared"
# Shelf order on the demo card: Game Boy, Game Boy Color, Game Boy Advance, music.
shot hub            --sys 2
shot hub-music      --sys 3
shot games          --sys 2 --screen games
shot albums         --sys 3 --screen games
shot now-playing    --nowplaying 2 1 41
shot menu           --sys 2 --screen games --menu 1
echo "screenshots in $OUT"
