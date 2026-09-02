"""
Generate the app icon: a rainbow swirl behind white speech bars.

Run once; produces icon.ico (multi-resolution) and icon.png.
    venv\\Scripts\\python.exe make_icon.py
"""

import colorsys
import math
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
SIZE = 512                      # drawn big, downsampled for crispness

TILE_IN = (58, 30, 105)         # violet glow centre
TILE_OUT = (10, 5, 22)          # near-black edge
BAR = (255, 255, 255)


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def build(size=SIZE):
    img = Image.new("RGB", (size, size), TILE_OUT)
    d = ImageDraw.Draw(img)
    cx, cy = size / 2, size / 2

    # Soft violet glow fading to the dark edge.
    glow_r = size * 0.75
    for r in range(int(glow_r), 0, -1):
        t = r / glow_r
        col = tuple(int(TILE_OUT[i] + (TILE_IN[i] - TILE_OUT[i]) * (1 - t) ** 1.6)
                    for i in range(3))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)

    # Rainbow Archimedean spiral.
    turns = 3.0
    steps = 900
    dot = size * 0.02
    for i in range(steps):
        t = i / (steps - 1)
        theta = t * turns * 2 * math.pi
        r = size * 0.05 + t * size * 0.33
        hue = (t * turns) % 1.0
        rgb = colorsys.hsv_to_rgb(hue, 0.9, 1.0)
        col = tuple(int(c * 255) for c in rgb)
        x = cx + r * math.cos(theta)
        y = cy + r * math.sin(theta)
        d.ellipse([x - dot, y - dot, x + dot, y + dot], fill=col)

    # White waveform on top - taller in the middle, like speech energy.
    bars = 7
    span = size * 0.56
    bw = span / (bars * 2 - 1)
    x0 = (size - span) / 2
    mid = size / 2
    heights = [0.20, 0.40, 0.68, 0.92, 0.68, 0.40, 0.20]
    for i, frac in enumerate(heights):
        frac *= 1 + 0.05 * math.sin(i * 1.7)
        h = frac * size * 0.40
        x = x0 + i * bw * 2
        d.rounded_rectangle(
            [x, mid - h / 2, x + bw, mid + h / 2],
            radius=bw / 2, fill=BAR,
        )
        # A hint of the rainbow bleeding through each bar's base.
        under = colorsys.hsv_to_rgb(i / bars, 0.85, 1.0)
        ucol = tuple(int(c * 200) for c in under)
        d.rounded_rectangle(
            [x, mid + h / 2 - bw * 0.4, x + bw, mid + h / 2],
            radius=bw / 4, fill=ucol,
        )

    out = img.convert("RGBA")
    out.putalpha(rounded_mask(size, radius=int(size * 0.23)))
    return out


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
