#!/usr/bin/env bash
# Put the Zune launcher on a TortOS card, or take it off again.
#
#   scripts/install-to-card.sh /path/to/TORTOS            install
#   scripts/install-to-card.sh /path/to/TORTOS --restore  back to stock
#
# The path is the card's TORTOS drive as your computer mounts it (on a Mac
# /Volumes/TORTOS, on Linux usually /media/$USER/TORTOS). The stock launcher
# is kept beside the new one as tortos.elf.stock, so --restore - or copying
# that file back by hand - undoes everything.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
CARD=${1:-}
MODE=${2:-install}
DIST=$ROOT/dist/TortOS

[ -n "$CARD" ] || { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
T=$CARD/TortOS
[ -f "$T/tortos.elf" ] || { echo "no TortOS/tortos.elf on $CARD - is that the TORTOS drive?" >&2; exit 1; }

if [ "$MODE" = --restore ]; then
	[ -f "$T/tortos.elf.stock" ] || { echo "no tortos.elf.stock to restore" >&2; exit 1; }
	cp "$T/tortos.elf.stock" "$T/tortos.elf"
	sync
	echo "restored the stock launcher. (The Zune fonts in TortOS/fonts are harmless to leave.)"
	exit 0
fi

[ -f "$DIST/tortos.elf" ] || { echo "no build in dist/ - run scripts/build-pixel2.sh" >&2; exit 1; }
want=$(cat "$DIST/ZUNE_FOR_VERSION")
have=$(cat "$T/VERSION" 2>/dev/null || echo unknown)
if [ "$have" != "$want" ]; then
	echo "this card has TortOS $have, and this build is for $want." >&2
	echo "the launcher talks to the emulator and the music player beside it, so" >&2
	echo "the two have to be the same release. Flash TortOS $want first, or" >&2
	echo "rebuild against $have (tortos-zune/UPSTREAM)." >&2
	exit 1
fi

# Back up the stock launcher once. Never over an existing backup: running this
# twice must not replace the real stock file with the Zune one.
[ -f "$T/tortos.elf.stock" ] || cp "$T/tortos.elf" "$T/tortos.elf.stock"
mkdir -p "$T/fonts"
cp "$DIST"/fonts/* "$T/fonts/"
cp "$DIST/tortos.elf" "$T/tortos.elf.new"
mv -f "$T/tortos.elf.new" "$T/tortos.elf"
sync
echo "installed. Eject the card, put it in the Pixel 2 and power on."
echo "If the theme is not Zune already: MENU > UI Theme > Zune."
