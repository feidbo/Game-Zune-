#!/usr/bin/env bash
# Build the Zune launcher for the GKD Pixel 2, into dist/TortOS/.
#
# TortOS at the pinned release, plus the Zune patch, cross-compiled for
# aarch64 and linked against the SDL libraries taken out of that release's own
# Pixel 2 image - so it needs no device and no adb, and what it links against
# is exactly what the handheld runs.
#
# Needs: git curl xz python3 debugfs (e2fsprogs) make aarch64-linux-gnu-gcc
#   Debian/Ubuntu: apt install git curl xz-utils python3 e2fsprogs make gcc-aarch64-linux-gnu
set -euo pipefail
. "$(dirname "$0")/common.sh"
need git curl xz python3 debugfs make aarch64-linux-gnu-gcc aarch64-linux-gnu-strip sha256sum

DL=$WORK/downloads
SYSROOT=$WORK/sysroot-pixel2
mkdir -p "$DL"

# ---- the sysroot: the image's SDL, and matching headers ---------------------
if [ ! -f "$SYSROOT/.done" ]; then
	echo "sysroot: fetching the TortOS $TORTOS_VERSION Pixel 2 image"
	img_xz=$DL/$(basename "$PIXEL2_IMAGE_URL")
	fetch "$PIXEL2_IMAGE_URL" "$PIXEL2_IMAGE_SHA256" "$img_xz"
	img=${img_xz%.xz}
	# Unpacked beside it first, so a stopped run never leaves half an image
	# that the next one would take for whole.
	if [ ! -f "$img" ]; then
		xz -dc "$img_xz" > "$img.part"
		mv "$img.part" "$img"
	fi

	# The root filesystem is the image's Linux partition (MBR type 0x83).
	read -r start count < <(python3 - "$img" <<'PY'
import struct, sys
mbr = open(sys.argv[1], 'rb').read(512)
for i in range(4):
    e = mbr[446 + 16 * i: 446 + 16 * (i + 1)]
    if e[4] == 0x83:
        print(*struct.unpack('<II', e[8:16]))
        break
PY
) || true
	[ -n "${start:-}" ] || { echo "no Linux partition in $img" >&2; exit 1; }
	dd if="$img" of="$DL/rootfs.ext4" bs=512 skip="$start" count="$count" status=none

	rm -rf "$SYSROOT" "$DL/usr-lib"
	mkdir -p "$SYSROOT/usr/lib" "$SYSROOT/usr/include/SDL2" "$DL/usr-lib"
	# debugfs splits its command on spaces: the path is quoted for it.
	debugfs -R "rdump /usr/lib \"$DL/usr-lib\"" "$DL/rootfs.ext4" > /dev/null 2>&1
	cp -a "$DL"/usr-lib/lib/libSDL2* "$SYSROOT/usr/lib/"
	ls "$SYSROOT/usr/lib/libSDL2-2.0.so.0" "$SYSROOT/usr/lib/libSDL2_ttf-2.0.so.0" \
	   "$SYSROOT/usr/lib/libSDL2_image-2.0.so.0" > /dev/null

	echo "sysroot: fetching SDL headers"
	fetch "$SDL_URL" "$SDL_SHA256" "$DL/$(basename "$SDL_URL")"
	fetch "$TTF_URL" "$TTF_SHA256" "$DL/$(basename "$TTF_URL")"
	fetch "$IMG_URL" "$IMG_SHA256" "$DL/$(basename "$IMG_URL")"
	rm -rf "$DL/hdr" && mkdir -p "$DL/hdr"
	for f in "$SDL_URL" "$TTF_URL" "$IMG_URL"; do
		tar xzf "$DL/$(basename "$f")" -C "$DL/hdr"
	done
	cp "$DL"/hdr/SDL2-*/include/*.h "$SYSROOT/usr/include/SDL2/"
	cp "$DL"/hdr/SDL2_ttf-*/SDL_ttf.h "$SYSROOT/usr/include/SDL2/" 2>/dev/null ||
		cp "$DL"/hdr/SDL2_ttf-*/include/SDL_ttf.h "$SYSROOT/usr/include/SDL2/"
	cp "$DL"/hdr/SDL2_image-*/include/SDL_image.h "$SYSROOT/usr/include/SDL2/"
	touch "$SYSROOT/.done"
fi

# ---- the launcher ------------------------------------------------------------
T=$(tortos_tree) || exit 1
echo "build: TortOS $TORTOS_VERSION + Zune, for the Pixel 2"
# The image's SDL is built for KMS/DRM, and the Pixel's display code reads the
# DRM handle through SDL_syswm.h - which only declares it when the config
# says the driver is there. The generic headers cannot know that, so it is
# said here.
make -C "$T" -f mk/cross.mk DEVICE=pixel2 SYSROOT="$SYSROOT" \
     CC="aarch64-linux-gnu-gcc -DSDL_VIDEO_DRIVER_KMSDRM=1" \
     VERSION="$TORTOS_VERSION" creds build/tortos.elf > "$WORK/build.log" 2>&1 ||
	{ grep -E 'error' "$WORK/build.log" >&2 || true; echo "build failed: see $WORK/build.log" >&2; exit 1; }

OUT=$ROOT/dist/TortOS
mkdir -p "$OUT/fonts"
aarch64-linux-gnu-strip -o "$OUT/tortos.elf" "$T/build/tortos.elf"
cp "$ROOT"/tortos-zune/fonts/*.ttf "$ROOT"/tortos-zune/fonts/OFL-Selawik.txt "$OUT/fonts/"
cp "$ROOT"/tortos-zune/zune-wallpaper.jpg "$OUT/"
echo "$TORTOS_VERSION" > "$OUT/ZUNE_FOR_VERSION"
echo "done: $OUT"
ls -l "$OUT" "$OUT/fonts"
