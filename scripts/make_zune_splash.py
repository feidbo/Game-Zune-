#!/usr/bin/env python3
"""The Zune boot animation for the GKD Pixel 2, in the format its splash plays.

    python3 scripts/make_zune_splash.py      # writes dist/TortOS/zune-splash.bin

The Pixel 2's first picture at power-on is TortOS's splash (/usr/bin/splash in
the system image), which plays /usr/share/splash/frames.bin until the launcher
takes the display. The Zune launcher puts this file there in place of TortOS's
animation, keeping the original beside it to put back (src/main.c,
zune_splash_sync).

THE FORMAT, read off the stock file: "TSPL", then little-endian u16 width,
height, frame count and frames per second, then a u32 offset per frame, then
each frame as runs of (u32 count, u32 pixel), pixels XRGB8888, the frame
width x height in the panel's own orientation - 480 x 640, the 640 x 480
picture turned a quarter counter-clockwise, as the launcher turns it.

Runs mean flat color is cheap and a gradient is not, so the animation is drawn
in flat shapes: a bloom of the Zune's colors that gathers into the white
"zune" wordmark, which holds until the launcher's first frame. Frame 0 is
black, as the panel is when the splash starts.
"""
import math
import os
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dist", "TortOS", "zune-splash.bin")
PREVIEW = os.path.join(ROOT, "docs", "screenshots", "zune-splash.gif")
FONT = os.path.join(ROOT, "dist", "TortOS", "fonts", "zune-light.ttf")

W, H = 640, 480                 # as seen
FPS = 30
FRAMES = 48                     # 1.6 s, then the last frame holds
SS = 2                          # drawn at twice the size, then reduced
LEVELS = 6                      # shades an edge may take: a few runs, not a gradient

# The Zune's own colors: orange, magenta, purple, blue, teal, green.
PETALS = [0xF26522, 0xEC008C, 0x92278F, 0x00AEEF, 0x00A99D, 0x8DC63F]
BG = (0, 0, 0)


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def rgb(c):
    return ((c >> 16) & 255, (c >> 8) & 255, c & 255)


def frame(i, font):
    """Frame i, 640 x 480 RGB."""
    im = Image.new("RGB", (W * SS, H * SS), BG)
    d = ImageDraw.Draw(im)
    cx, cy = W * SS / 2, H * SS / 2 - 10 * SS
    t = i / (FRAMES - 1)

    # The bloom: six petals open from the middle (0 - 0.45), then turn about
    # and fold back into it (0.45 - 0.7), leaving the word.
    if 0.04 < t < 0.72:
        grow = ease_out((t - 0.04) / 0.36)
        fold = ease_in_out((t - 0.45) / 0.27)
        spin = 0.9 * ease_in_out((t - 0.04) / 0.68)
        for k, c in enumerate(PETALS):
            a = spin + k * 2 * math.pi / len(PETALS)
            dist = 120 * SS * grow * (1 - fold)
            r = 78 * SS * grow * (1 - 0.85 * fold)
            x, y = cx + dist * math.cos(a), cy + dist * math.sin(a) * 0.82
            if r > 1:
                d.ellipse((x - r, y - r, x + r, y + r), fill=rgb(c))

    # The word fades in white as the bloom folds, then holds.
    shade = ease_in_out((t - 0.48) / 0.3)
    if shade > 0:
        v = int(255 * shade)
        word = "zune"
        box = d.textbbox((0, 0), word, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        d.text((cx - tw / 2 - box[0], cy - th / 2 - box[1]), word, font=font, fill=(v, v, v))
        # A short magenta line beneath it, drawn out left to right.
        line = ease_out((t - 0.7) / 0.25)
        if line > 0:
            lw = 140 * SS * line
            y0 = cy + th / 2 + 34 * SS
            d.rectangle((cx - 70 * SS, y0, cx - 70 * SS + lw, y0 + 5 * SS), fill=rgb(0xEC008C))

    im = im.resize((W, H), Image.LANCZOS)
    return posterize_edges(im)


def posterize_edges(im):
    """Each pixel snapped to LEVELS steps between black and its own hue, so
    antialiased edges come in a handful of shades and the runs stay long."""
    step = 255 / (LEVELS - 1)
    return im.point(lambda v: int(round(v / step) * step))


def encode(frames):
    """The TSPL file for frames (each 640 x 480 RGB, as seen)."""
    blobs = []
    for im in frames:
        panel = im.rotate(90, expand=True)          # 480 x 640, a quarter counter-clockwise
        px = panel.tobytes("raw", "RGB")
        runs = bytearray()
        prev, count = None, 0
        for o in range(0, len(px), 3):
            v = 0xFF000000 | (px[o] << 16) | (px[o + 1] << 8) | px[o + 2]
            if v == prev:
                count += 1
            else:
                if prev is not None:
                    runs += struct.pack("<II", count, prev)
                prev, count = v, 1
        runs += struct.pack("<II", count, prev)
        blobs.append(bytes(runs))
    pw, ph = H, W
    head = struct.pack("<4sHHHH", b"TSPL", pw, ph, len(frames), FPS)
    at = len(head) + 4 * len(frames)
    offs = []
    for b in blobs:
        offs.append(at)
        at += len(b)
    return head + struct.pack("<%dI" % len(frames), *offs) + b"".join(blobs)


def decode(data):
    """(width, height, fps, [RGB frames as seen]) - to check a file."""
    magic, w, h, n, fps = struct.unpack("<4sHHHH", data[:12])
    if magic != b"TSPL":
        raise ValueError("not a splash file")
    offs = list(struct.unpack("<%dI" % n, data[12:12 + 4 * n])) + [len(data)]
    out = []
    for i in range(n):
        px = bytearray()
        blob = data[offs[i]:offs[i + 1]]
        for k in range(0, len(blob), 8):
            c, v = struct.unpack("<II", blob[k:k + 8])
            px += struct.pack("<I", v) * c
        if len(px) != w * h * 4:
            raise ValueError("frame %d is %d pixels, not %d" % (i, len(px) // 4, w * h))
        panel = Image.frombytes("RGBA", (w, h), bytes(px), "raw", "BGRA").convert("RGB")
        out.append(panel.rotate(-90, expand=True))
    return w, h, fps, out


def main():
    if not os.path.exists(FONT):
        sys.exit("no %s - the Zune fonts come with the launcher" % FONT)
    font = ImageFont.truetype(FONT, 120 * SS)
    frames = [frame(i, font) for i in range(FRAMES)]
    data = encode(frames)
    w, h, fps, back = decode(data)
    assert (w, h, fps, len(back)) == (H, W, FPS, FRAMES)
    assert back[-1].tobytes() == frames[-1].tobytes(), "the round trip changed a frame"
    assert max(frames[0].getextrema(), key=lambda e: e[1])[1] == 0, "frame 0 must be black"
    with open(OUT + ".new", "wb") as f:
        f.write(data)
    os.replace(OUT + ".new", OUT)
    os.makedirs(os.path.dirname(PREVIEW), exist_ok=True)
    frames[0].save(PREVIEW, save_all=True, append_images=frames[1:] + [frames[-1]] * 20,
                   duration=int(1000 / FPS), loop=0)
    print("%s: %d frames, %.1f KB (TortOS's is 2,608 KB)" % (os.path.relpath(OUT, ROOT), FRAMES,
                                                             len(data) / 1024))


if __name__ == "__main__":
    main()
