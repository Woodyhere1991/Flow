"""
Generate the app icon: a waveform inside a rounded gradient tile.

Run once; produces icon.ico (multi-resolution) and icon.png.
    venv\\Scripts\\python.exe make_icon.py
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
SIZE = 512                      # drawn big, downsampled for crispness

TOP = (124, 92, 255)            # violet
BOTTOM = (56, 189, 248)         # cyan
BAR = (255, 255, 255)


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def gradient(size, top, bottom):
    g = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(size - 1, 1)
        g.putpixel((0, y), tuple(
            int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)
        ))
    return g.resize((size, size))


def build(size=SIZE):
    base = gradient(size, TOP, BOTTOM).convert("RGBA")
    base.putalpha(rounded_mask(size, radius=int(size * 0.23)))

    d = ImageDraw.Draw(base)

    # A symmetric waveform - taller in the middle, like speech energy.
    bars = 7
    span = size * 0.60
    bw = span / (bars * 2 - 1)
    x0 = (size - span) / 2
    mid = size / 2
    heights = [0.20, 0.40, 0.68, 0.92, 0.68, 0.40, 0.20]

    for i, frac in enumerate(heights):
        # Slight organic variation so it doesn't look mechanically generated.
        frac *= 1 + 0.05 * math.sin(i * 1.7)
        h = frac * size * 0.42
        x = x0 + i * bw * 2
        d.rounded_rectangle(
            [x, mid - h / 2, x + bw, mid + h / 2],
            radius=bw / 2, fill=BAR,
        )
    return base


def main():
    img = build()
    img.save(HERE / "icon.png")

    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [img.resize((s, s), Image.LANCZOS) for s in sizes]
    frames[-1].save(HERE / "icon.ico", format="ICO",
                    sizes=[(s, s) for s in sizes])
    print("wrote", HERE / "icon.ico")
    print("wrote", HERE / "icon.png")


if __name__ == "__main__":
    main()
