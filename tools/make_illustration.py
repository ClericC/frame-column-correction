"""Own illustration of column banding: a simple scene, once clean and once with alternating column brightness."""
# Copyright (c) 2026 ClericC - MIT License - https://github.com/ClericC/frame-column-correction
# Usage: python3 tools/make_illustration.py docs/screenshots   (needs numpy + Pillow + DejaVu fonts)
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, S = 200, 150, 3          # scene in "display pixels"; each shown as S x S screen pixels
yy, xx = np.mgrid[0:H, 0:W].astype(float)

def scene():
    # drawn at 4x and scaled down for smooth edges, in final screen size
    SS = 4; w, h = W * S * SS, H * S * SS
    y, x = np.mgrid[0:h, 0:w].astype(float)
    img = np.array([0.36, 0.66, 0.16]) * (0.85 + 0.25 * (1 - y / h))[..., None]
    img[y > h * 0.78] = [0.05, 0.06, 0.09]
    im = Image.fromarray((img * 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    k = S * SS
    P = lambda pts: [(px * k, py * k) for px, py in pts]
    d.polygon(P([(40, 0), (150, 0), (175, 40), (120, 82), (55, 70)]), fill=(178, 180, 190))
    d.polygon(P([(120, 82), (175, 40), (200, 30), (200, 75)]), fill=(128, 130, 142))
    d.polygon(P([(40, 0), (55, 70), (15, 55), (0, 10), (0, 0)]), fill=(150, 152, 163))
    im = im.resize((W * S, H * S), Image.LANCZOS)
    return np.asarray(im).astype(float) / 255

def banding(img):
    # neighbouring display-pixel columns (S screen pixels wide) differ in brightness;
    # strongest on mid tones (grey, green, blue), weak on dark areas
    hh, ww = img.shape[:2]
    col = ((np.arange(ww) // S) % 2 * 2 - 1)[None, :].repeat(hh, 0)
    lum = img.mean(axis=2)
    amount = 0.13 * np.clip(lum / 0.35, 0, 1)
    out = img * (1 + amount * col)[..., None]
    out[..., 0] *= 1 + 0.03 * col
    out[..., 2] *= 1 - 0.03 * col
    return np.clip(out, 0, 1)

def to_screen(img):
    im = Image.fromarray((img * 255).astype(np.uint8))
    im = im.filter(ImageFilter.GaussianBlur(0.7))            # a little lens softness
    v = np.asarray(im).astype(float)
    hh, ww = v.shape[:2]
    y, x = np.mgrid[0:hh, 0:ww]
    vign = 1 - 0.25 * (((x - ww / 2) / (ww / 2)) ** 2 + ((y - hh / 2) / (hh / 2)) ** 2)
    return Image.fromarray(np.clip(v * vign[..., None], 0, 255).astype(np.uint8))

LABELS = {
    "en": ("Without correction: stripes", "With correction: no stripes", "Illustration, not a photo"),
    "ru": ("Без коррекции: полосы", "С коррекцией: полос нет", "Иллюстрация, не фото"),
    "de": ("Ohne Korrektur: Streifen", "Mit Korrektur: keine Streifen", "Illustration, kein Foto"),
}
base = scene()
a, b = to_screen(banding(base)), to_screen(base)
F = "/usr/share/fonts/truetype/dejavu/"
for lang, (la, lb, note) in LABELS.items():
    pad, bar = 16, 56
    out = Image.new("RGB", (a.width * 2 + pad * 3, a.height + bar + pad * 2 + 30), (246, 248, 250))
    out.paste(a, (pad, pad)); out.paste(b, (a.width + pad * 2, pad))
    d = ImageDraw.Draw(out)
    f, fs = ImageFont.truetype(F + "DejaVuSans-Bold.ttf", 22), ImageFont.truetype(F + "DejaVuSans.ttf", 16)
    for i, (t, col) in enumerate(((la, (190, 60, 50)), (lb, (40, 130, 60)))):
        x = pad + i * (a.width + pad) + a.width // 2
        d.text((x, pad + a.height + 30), t, font=f, fill=col, anchor="mm")
    d.text((out.width // 2, out.height - 22), note, font=fs, fill=(110, 118, 128), anchor="mm")
    out.save(f"{sys.argv[1]}/stripes-{lang}.png", optimize=True)
print("ok")
