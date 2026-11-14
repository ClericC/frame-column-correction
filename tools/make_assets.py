# Copyright (c) 2026 ClericC - MIT License - https://github.com/ClericC/frame-column-correction
"""Build-time only: pre-render DejaVu Sans glyphs (Latin + Cyrillic) and the icons for Frame VCOM.
The headset has no Python imaging library, so the app ships these bitmaps instead of rasterising fonts."""
import json, sys
from PIL import Image, ImageDraw, ImageFont

OUT = sys.argv[1]
FD = "/usr/share/fonts/truetype/dejavu/"
FONTS = {"xs": ("DejaVuSans.ttf", 14), "s": ("DejaVuSans.ttf", 24), "m": ("DejaVuSans.ttf", 30), "mb": ("DejaVuSans-Bold.ttf", 30),
         "l": ("DejaVuSans-Bold.ttf", 38), "xl": ("DejaVuSans-Bold.ttf", 84)}
CHARS = [chr(c) for c in range(32, 127)] + [chr(c) for c in range(0xA0, 0x100)] + [chr(c) for c in range(0x410, 0x450)] + ["Ё", "ё"] + list("°±−–—…·×→≤≥„“”‘’")

meta, blob = {}, bytearray()
for key, (file, size) in FONTS.items():
    f = ImageFont.truetype(FD + file, size)
    asc, desc = f.getmetrics()
    glyphs = {}
    for ch in CHARS:
        adv = round(f.getlength(ch))
        x0, y0, x1, y1 = f.getbbox(ch, anchor="ls")
        w, h = max(0, x1 - x0), max(0, y1 - y0)
        if w and h:
            im = Image.new("L", (w, h), 0)
            ImageDraw.Draw(im).text((-x0, -y0), ch, font=f, fill=255, anchor="ls")
            data = im.tobytes()
        else:
            data = b""
        glyphs[str(ord(ch))] = [w, h, x0, y0, adv, len(blob)]
        blob += data
    meta[key] = {"ascent": asc, "descent": desc, "glyphs": glyphs}
open(OUT + "/glyphs.bin", "wb").write(bytes(blob))
json.dump(meta, open(OUT + "/glyphs.json", "w"), separators=(",", ":"))

# Icon: a small display with vertical stripes being evened out (own design)
def icon(size):
    s = size / 128
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([4 * s, 4 * s, 124 * s, 124 * s], radius=24 * s, fill=(28, 33, 41, 255))
    d.rounded_rectangle([20 * s, 30 * s, 108 * s, 92 * s], radius=8 * s, fill=(60, 120, 200, 255))
    for i in range(11):  # stripes fading out from left to right
        x = 24 * s + i * 8 * s
        a = max(0, 200 - i * 22)
        d.rectangle([x, 34 * s, x + 3 * s, 88 * s], fill=(20, 40, 80, a))
    d.rectangle([44 * s, 98 * s, 84 * s, 104 * s], fill=(120, 200, 130, 255))
    return im
icon(128).save(OUT + "/icon.png")
icon(256).save(OUT + "/icon256.png")
print("glyph bytes:", len(blob))
