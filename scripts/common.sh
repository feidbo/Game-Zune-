# Shared by the scripts here: where things are, and the pinned upstream.
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
WORK=${WORK:-$ROOT/.work}
# shellcheck source=../tortos-zune/UPSTREAM
. "$ROOT/tortos-zune/UPSTREAM"

need() {
	local missing= c
	for c in "$@"; do command -v "$c" > /dev/null 2>&1 || missing="$missing $c"; done
	if [ -n "$missing" ]; then
		echo "missing tools:$missing" >&2
		exit 1
	fi
}

# fetch URL SHA256 FILE: download once, and refuse anything that does not
# match the pinned hash.
fetch() {
	local url=$1 sha=$2 out=$3 got
	if [ ! -f "$out" ]; then
		mkdir -p "$(dirname "$out")"
		curl -sSfL -o "$out.part" "$url" || { rm -f "$out.part"; echo "could not download $url" >&2; exit 1; }
		mv "$out.part" "$out"
	fi
	got=$(sha256sum "$out" | cut -d' ' -f1)
	if [ "$got" != "$sha" ]; then
		echo "hash mismatch for $out: got $got, want $sha" >&2
		rm -f "$out"
		exit 1
	fi
}

# TortOS at the pinned commit with the Zune patches applied, in $WORK/tortos.
# Reset every time, so the tree is always exactly upstream + the patches.
# Called as T=$(tortos_tree) || exit 1: inside $( ) set -e does not stop
# anything, so each step says for itself when it failed.
tortos_tree() {
	local t=$WORK/tortos
	if [ ! -d "$t/.git" ]; then
		git clone -q "$TORTOS_REPO" "$t" || return 1
	fi
	git -C "$t" fetch -q --tags origin || return 1
	git -C "$t" checkout -q -f "$TORTOS_COMMIT" || return 1
	git -C "$t" clean -qfdx -e build -e build-native || return 1
	git -C "$t" apply "$ROOT"/tortos-zune/patches/*.patch ||
		{ echo "the Zune patches do not apply to TortOS $TORTOS_COMMIT" >&2; return 1; }
	echo "$t"
}
