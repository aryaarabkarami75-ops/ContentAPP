#!/usr/bin/env python3
"""Brand helpers for the banner skill.

python brand_tools.py palette <image>                 -> dominant colours (hex, share) + suggested roles
python brand_tools.py crop-logo <image> x y w h <out> -> crop a logo (box normalised 0-1), key out a flat background
"""
import json
import sys

import numpy as np
from PIL import Image


def palette(path, k=6):
    im = Image.open(path).convert("RGB")
    im.thumbnail((80, 80))
    px = np.asarray(im, dtype=np.float32).reshape(-1, 3)
    centers = px[np.linspace(0, len(px) - 1, k).astype(int)].copy()
    for _ in range(12):
        d = ((px[:, None, :] - centers[None]) ** 2).sum(2)
        a = d.argmin(1)
        for j in range(k):
            if (a == j).any():
                centers[j] = px[a == j].mean(0)
    share = np.bincount(a, minlength=k) / len(px)
    cols = sorted(((("#%02x%02x%02x" % tuple(int(v) for v in centers[j])), float(share[j])) for j in range(k) if share[j] > 0.01), key=lambda t: -t[1])
    hexes = [c for c, _ in cols]
    return {"palette": cols, "roles": roles(hexes)}


def roles(hexes):
    to = lambda h: [int(h[i:i + 2], 16) for i in (1, 3, 5)]
    sat = lambda h: (max(to(h)) - min(to(h))) / max(1, max(to(h)))
    light = lambda h: (0.299 * to(h)[0] + 0.587 * to(h)[1] + 0.114 * to(h)[2]) / 255
    dist = lambda a, b: sum((x - y) ** 2 for x, y in zip(to(a), to(b))) ** 0.5
    bg = hexes[0] if hexes else "#101828"
    others = [h for h in hexes[1:] if dist(h, bg) > 60]
    accent = sorted(others, key=sat, reverse=True)[0] if others else "#ff5a1f"
    primary = next((h for h in others if h != accent), accent)
    return {"background": bg, "primary": primary, "accent": accent,
            "text": "#111111" if light(bg) > 0.55 else "#ffffff", "ctaText": "#111111" if light(accent) > 0.6 else "#ffffff"}


def crop_logo(path, x, y, w, h, out):
    im = Image.open(path).convert("RGBA")
    W, H = im.size
    pad = 0.01
    box = (max(0, int((x - pad) * W)), max(0, int((y - pad) * H)), min(W, int((x + w + pad) * W)), min(H, int((y + h + pad) * H)))
    c = np.asarray(im.crop(box)).copy()
    corners = np.array([c[0, 0, :3], c[0, -1, :3], c[-1, 0, :3], c[-1, -1, :3]], dtype=float)
    avg = corners.mean(0)
    flat = bool((np.linalg.norm(corners - avg, axis=1) < 24).all())
    if flat:
        d = np.linalg.norm(c[..., :3].astype(float) - avg, axis=2)
        alpha = np.clip((d - 28) / 32, 0, 1)
        c[..., 3] = (c[..., 3] * alpha).astype(np.uint8)
    img = Image.fromarray(c, "RGBA")
    bb = img.getbbox()
    if bb:
        img = img.crop(bb)
    img.save(out)
    return {"logo": out, "background_removed": flat, "size": img.size}


if __name__ == "__main__":
    if sys.argv[1] == "palette":
        print(json.dumps(palette(sys.argv[2]), indent=2))
    elif sys.argv[1] == "crop-logo":
        a = sys.argv
        print(json.dumps(crop_logo(a[2], *map(float, a[3:7]), a[7])))
