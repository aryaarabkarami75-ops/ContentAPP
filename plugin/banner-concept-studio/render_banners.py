#!/usr/bin/env python3
"""Banner Studio renderer (runs inside ChatGPT's Python tool).

Turns approved, text-free artwork + copy + brand into every size of the chosen
ad placements, with Persian (RTL) text, logo, CTA, file-size limits and a ZIP.

Usage:  python render_banners.py job.json
job.json:
{
  "name": "wallgold",                          # used for file names
  "art": ["landscape.png", "square.png", "portrait.png", "wide.png"],
  "copy": {"headline": "...", "sub": "...", "cta": "..."},
  "brand": {
    "colors": {"background": "#5a0f1e", "primary": "#8a1c2c", "accent": "#e8b23a", "text": "#ffffff", "ctaText": "#1a1a1a"},
    "logo": "logo.png",                        # optional
    "logo_bg": "#5a0f1e"                       # optional, background of the Menchers round logo
  },
  "placements": ["web-dynamic", "menchers"],   # ids from placements.json, or "all"
  "text_on_image_only_slots": false,
  "flip_art": false,
  "out": "output"
}
Prints a JSON summary; writes <out>/<placement>/..., <out>/preview.png and <name>-banners.zip.
"""
import io
import json
import math
import os
import re
import sys
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "vendor"))
FONT_HEAD = os.path.join(HERE, "fonts", "Vazirmatn-FD-ExtraBold.ttf")
FONT_BODY = os.path.join(HERE, "fonts", "Vazirmatn-FD-Medium.ttf")
FONT_CTA = os.path.join(HERE, "fonts", "Vazirmatn-FD-Bold.ttf")
RAQM = features.check("raqm")
RTL_RE = re.compile(r"[֐-ࣿיִ-ﻼ]")

# ---------------------------------------------------------------- text shaping
_reshaper = None


def _visual(text):
    """Shape + reorder RTL text for PIL builds without raqm."""
    global _reshaper
    if _reshaper is None:
        import arabic_reshaper  # vendored
        _reshaper = arabic_reshaper.ArabicReshaper(configuration={"delete_harakat": False, "support_ligatures": True})
    shaped = _reshaper.reshape(text)
    # Reverse for RTL, but keep runs of Latin letters/digits left-to-right.
    runs = re.findall(r"[A-Za-z0-9۰-۹٠-٩.,%:/+\-]+|[^A-Za-z0-9۰-۹٠-٩.,%:/+\-]+", shaped)
    out = []
    for r in reversed(runs):
        out.append(r if re.match(r"[A-Za-z0-9۰-۹٠-٩]", r) else r[::-1])
    s = "".join(out)
    return s.translate(str.maketrans("()[]{}«»", ")(][}{»«"))


class Text:
    def __init__(self, path, size):
        self.font = ImageFont.truetype(path, max(6, int(size)), layout_engine=ImageFont.Layout.RAQM if RAQM else ImageFont.Layout.BASIC)
        self.size = int(size)

    def prep(self, s):
        if RTL_RE.search(s or "") and not RAQM:
            return _visual(s), {}
        return s, ({"direction": "rtl"} if RAQM and RTL_RE.search(s or "") else {})

    def width(self, s):
        t, kw = self.prep(s)
        return self.font.getlength(t, **kw)

    def draw(self, draw, xy, s, fill, anchor="la"):
        t, kw = self.prep(s)
        draw.text(xy, t, font=self.font, fill=fill, anchor=anchor, **kw)


def wrap(text, font, max_w):
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        t = f"{cur} {w}" if cur else w
        if font.width(t) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit(text, path, max_w, max_h, max_size, min_size, max_lines, lh=1.3):
    if not text:
        return None
    size = int(max_size)
    while size >= min_size:
        f = Text(path, size)
        lines = wrap(text, f, max_w)
        if len(lines) <= max_lines and max(f.width(l) for l in lines) <= max_w and len(lines) * size * lh <= max_h:
            return {"font": f, "lines": lines, "size": size, "lh": lh, "height": len(lines) * size * lh}
        size -= max(1, round(size * 0.04))
    return None


def draw_block(draw, block, x, y, align, color):
    for i, line in enumerate(block["lines"]):
        w = block["font"].width(line)
        lx = x if align == "left" else x - w if align == "right" else x - w / 2
        block["font"].draw(draw, (lx, y + i * block["size"] * block["lh"]), line, color)


# ---------------------------------------------------------------- colour
def rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lum(h):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    x, y = sorted([lum(a), lum(b)], reverse=True)
    return (x + 0.05) / (y + 0.05)


def readable(pref, bg):
    if pref and contrast(pref, bg) >= 4.5:
        return pref
    return "#ffffff" if contrast("#ffffff", bg) >= contrast("#111111", bg) else "#111111"


# ---------------------------------------------------------------- layout (mirrors client/src/lib/render.js)
def compute_layout(W, H, rtl=False, art_only=False, safe=None):
    r = W / H
    if art_only:
        return dict(mode="art", side="none", art=(0, 0, W, H), content=(0, 0, 0, 0), W=W, H=H, rtl=rtl)
    if r >= 2.6:
        wide = r > 5 and H >= 120
        aw = round(min(W * (0.5 if wide else 0.38), H * (3 if wide else 1.7)))
        art = (0 if rtl else W - aw, 0, aw, H)
        content = (aw if rtl else 0, 0, W - aw, H)
        mode, side = "strip", "none"
    elif r <= 0.5:
        ah = round(H * 0.46)
        art, content, mode, side = (0, 0, W, ah), (0, ah, W, H - ah), "tower", "none"
    else:
        mode, art = "full", (0, 0, W, H)
        side = ("right" if rtl else "left") if r >= 1.4 else "bottom"
        cw = round(W * 0.56)
        content = {"left": (0, 0, cw, H), "right": (W - cw, 0, cw, H)}.get(side, (0, round(H * 0.55), W, round(H * 0.45)))
    if safe:
        x1 = max(content[0], safe.get("left", 0) * W)
        y1 = max(content[1], safe.get("top", 0) * H)
        x2 = min(content[0] + content[2], W - safe.get("right", 0) * W)
        y2 = min(content[1] + content[3], H - safe.get("bottom", 0) * H)
        content = (x1, y1, x2 - x1, y2 - y1)
    return dict(mode=mode, side=side, art=art, content=content, W=W, H=H, rtl=rtl, top_inset=(safe or {}).get("top", 0) * H)


# ---------------------------------------------------------------- art
def smart_crop(img, W, H):
    """Scale to cover W×H and crop around the most detailed / colourful region."""
    img = img.convert("RGB")
    iw, ih = img.size
    s = max(W / iw, H / ih)
    cw, ch = W / s, H / s
    gs = 96 / max(iw, ih)
    gw, gh = max(8, round(iw * gs)), max(8, round(ih * gs))
    a = np.asarray(img.resize((gw, gh)), dtype=np.float32)
    l = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    mx, mn = a.max(2), a.min(2)
    e = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1) * 40, 0)
    e[:, :-1] += np.abs(np.diff(l, axis=1))
    e[:-1, :] += np.abs(np.diff(l, axis=0))
    wx, wy = max(1, round(cw * gs)), max(1, round(ch * gs))
    ii = np.pad(e.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    best, bx, by = -1, 0, 0
    for y0 in range(0, max(1, gh - wy + 1)):
        for x0 in range(0, max(1, gw - wx + 1)):
            y1, x1 = min(gh, y0 + wy), min(gw, x0 + wx)
            v = ii[y1, x1] - ii[y0, x1] - ii[y1, x0] + ii[y0, x0]
            if v > best:
                best, bx, by = v, x0, y0
    cw, ch = min(cw, iw), min(ch, ih)
    sx = max(0.0, min(iw - cw, bx / gs))
    sy = max(0.0, min(ih - ch, by / gs))
    return img.resize((W, H), Image.LANCZOS, box=(sx, sy, sx + cw, sy + ch))


def pick_art(arts, w, h):
    t = math.log(w / h)
    return min(arts, key=lambda im: abs(math.log(im.width / im.height) - t))


# ---------------------------------------------------------------- drawing helpers
def gradient(W, H, x0, y0, x1, y1, color, a0, a1):
    """Linear alpha gradient of one colour from (x0,y0)=a0 to (x1,y1)=a1, clamped outside."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dx, dy = x1 - x0, y1 - y0
    t = ((xx - x0) * dx + (yy - y0) * dy) / max(1e-6, dx * dx + dy * dy)
    t = np.clip(t, 0, 1)
    alpha = (a0 + (a1 - a0) * t) * 255
    layer = np.zeros((H, W, 4), dtype=np.uint8)
    layer[..., :3] = rgb(color)
    layer[..., 3] = alpha.astype(np.uint8)
    return Image.fromarray(layer, "RGBA")


def paste_logo(canvas, logo, x, y, max_w, max_h, align="left"):
    s = min(max_w / logo.width, max_h / logo.height)
    w, h = max(1, round(logo.width * s)), max(1, round(logo.height * s))
    lg = logo.resize((w, h), Image.LANCZOS)
    dx = x if align == "left" else x + max_w - w if align == "right" else x + (max_w - w) / 2
    canvas.alpha_composite(lg, (round(dx), round(y)))
    return h


def cta_size(label, h, max_w):
    size = round(h * 0.42)
    while True:
        f = Text(FONT_CTA, size)
        tw = f.width(label)
        if tw + size * 1.6 <= max_w or size <= 8:
            break
        size -= 1
    return f, math.ceil(min(max_w, tw + max(h * 1.1, size * 1.6)))


def draw_cta(canvas, label, x, y, h, w, font, colors):
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x, y + h * 0.06, x + w, y + h + h * 0.06), radius=h * 0.28, fill=(0, 0, 0, 70))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(max(1, h * 0.12))))
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((x, y, x + w, y + h), radius=h * 0.28, fill=rgb(colors["accent"]))
    font.draw(d, (x + w / 2 - font.width(label) / 2, y + h / 2), label, readable(colors.get("ctaText"), colors["accent"]), anchor="lm")


# ---------------------------------------------------------------- banner
def render_banner(W, H, art, logo, colors, copy, layout):
    c = dict(colors)
    if contrast(c["accent"], c["background"]) < 1.8:
        c["accent"] = c["primary"] if contrast(c.get("primary", "#000"), c["background"]) >= 1.8 else readable(None, c["background"])
    canvas = Image.new("RGBA", (W, H), rgb(c["background"]) + (255,))
    ax, ay, aw, ah = (round(v) for v in layout["art"])
    if art is not None:
        canvas.alpha_composite(art.convert("RGBA"), (ax, ay))
    warnings = []
    mode, side, rtl = layout["mode"], layout["side"], layout["rtl"]
    if mode == "art":
        return canvas, warnings
    bg = c["background"]
    if mode == "full" and side in ("left", "right"):
        g = gradient(W, H, 0 if side == "left" else W, 0, W * 0.7 if side == "left" else W * 0.3, 0, bg, 0.88, 0.0)
        canvas.alpha_composite(g)
    elif mode == "full":
        canvas.alpha_composite(gradient(W, H, 0, H, 0, H * 0.4, bg, 0.92, 0.0))
    elif mode == "strip":
        bw = aw * 0.45
        x0 = ax + aw if rtl else ax
        canvas.alpha_composite(gradient(W, H, x0, 0, x0 - bw if rtl else x0 + bw, 0, bg, 1.0, 0.0))
    elif mode == "tower":
        canvas.alpha_composite(gradient(W, H, 0, ah, 0, ah * 0.7, bg, 1.0, 0.0))

    d = ImageDraw.Draw(canvas)
    tc = readable(c.get("text"), bg)
    headline, sub, cta = copy.get("headline", ""), copy.get("sub", ""), copy.get("cta", "")
    md = min(W, H)
    pad = max(6, round(md * 0.07))
    cx, cy, cw, chh = layout["content"]
    box = (cx + pad, cy + pad, cw - 2 * pad, chh - 2 * pad)
    start = "right" if rtl else "left"

    # inline row for short strips (728×90, 468×60, 1081×144 ...)
    if mode == "strip" and H < 130:
        bx, by, bw_, bh = box
        X = (lambda dist, w=0: bx + bw_ - dist - w) if rtl else (lambda dist, w=0: bx + dist)
        dist = 0
        if logo is not None:
            lh = H * 0.42
            lw = min(bw_ * 0.18, logo.width / logo.height * lh)
            paste_logo(canvas, logo, X(dist, lw), (H - lh) / 2, lw, lh, start)
            dist += lw + pad
        ctaw = 0
        if cta:
            ch = round(max(18, H * 0.46))
            f, ctaw = cta_size(cta, ch, bw_ * 0.34)
            draw_cta(canvas, cta, X(bw_ - ctaw, ctaw), (H - ch) / 2, ch, ctaw, f, c)
            d = ImageDraw.Draw(canvas)
        tw = bw_ - ctaw - pad - dist
        two = H >= 70 and sub
        head = fit(headline, FONT_HEAD, tw, (0.6 if two else 1) * bh, bh * (0.5 if two else 0.62), 9, 2, 1.25)
        sb = fit(sub, FONT_BODY, tw, bh - head["height"] - 2, head["size"] * 0.6, 9, 1, 1.3) if (two and head) else None
        if not head:
            warnings.append("headline too long for this size")
        else:
            total = head["height"] + (sb["height"] + 2 if sb else 0)
            y = (H - total) / 2
            tx = bx + bw_ - dist if rtl else bx + dist
            draw_block(d, head, tx, y, start, tc)
            if sb:
                draw_block(d, sb, tx, y + head["height"] + 2, start, tc)
            elif sub:
                warnings.append("subtext dropped (no room)")
        return canvas, warnings

    align = start if (mode == "strip" or side in ("left", "right")) else "center"
    bx, by, bw_, bh = box
    axx = bx if align == "left" else bx + bw_ if align == "right" else bx + bw_ / 2
    top, avail = by, bh
    if logo is not None:
        lh = round(min(max(md * 0.09, 14), md * 0.14))
        if mode == "full":
            lw = md * 0.4
            lx = pad if align == "left" else W - pad - lw if align == "right" else (W - lw) / 2
            ly = layout.get("top_inset", 0) + pad
            paste_logo(canvas, logo, lx, ly, lw, lh, align)
            if side != "bottom":
                used = ly + lh + pad * 0.6 - top
                if used > 0:
                    top += used
                    avail -= used
        else:
            paste_logo(canvas, logo, bx, top, bw_, lh, align)
            top += lh + pad * 0.7
            avail -= lh + pad * 0.7
    ch = round(min(max(md * (0.2 if mode == "strip" else 0.11), 22), avail * 0.22)) if cta else 0
    gap = round(max(4, avail * 0.04))
    text_h = avail - (ch + gap * 1.6 if cta else 0)
    head_max = min(bw_ * 0.12, text_h * 0.42) if mode == "strip" else min(md * 0.15, text_h * 0.5)
    head, sb = None, None
    share = 0.62 if sub else 1
    for tries in range(4):
        head = fit(headline, FONT_HEAD, bw_, text_h * share, head_max * (1 - tries * 0.12), 10, 3, 1.3)
        if not head or not sub:
            break
        sb = fit(sub, FONT_BODY, bw_, text_h - head["height"] - gap, max(10, head["size"] * 0.46), max(9, round(md * 0.03)), 3, 1.45)
        if sb:
            break
        share -= 0.08
    if head and sub and not sb:
        warnings.append("subtext dropped (no room)")
    if not head and headline:
        warnings.append("headline too long for this size")
    block_h = (head["height"] if head else 0) + (gap + sb["height"] if sb else 0) + (gap * 1.6 + ch if cta else 0)
    y = top + avail - block_h if (mode == "full" and side == "bottom") else top + (avail - block_h) / 2
    if head:
        draw_block(d, head, axx, y, align, tc)
        y += head["height"]
    if sb:
        y += gap
        draw_block(d, sb, axx, y, align, tc)
        y += sb["height"]
    if cta:
        y += gap * 1.6
        f, w = cta_size(cta, ch, bw_)
        x = bx if align == "left" else bx + bw_ - w if align == "right" else bx + (bw_ - w) / 2
        draw_cta(canvas, cta, x, y, ch, w, f, c)
    return canvas, warnings


def render_round_logo(logo, bg_hex, size=512):
    """Menchers round logo: transparent 512×512, brand-colour disc, logo inside the 365px safe circle."""
    ss = 4
    big = size * ss
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((ss, ss, big - ss, big - ss), fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    disc = Image.new("RGBA", (size, size), rgb(bg_hex) + (255,))
    # soft light in the centre, like the kit's overlay layer
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    r = np.sqrt((xx - size / 2) ** 2 + (yy - size / 2) ** 2) / (size / 2)
    light = np.zeros((size, size, 4), dtype=np.uint8)
    light[..., :3] = 255
    light[..., 3] = (np.clip(1 - r, 0, 1) ** 1.6 * 70).astype(np.uint8)
    disc.alpha_composite(Image.fromarray(light, "RGBA"))
    dark = np.zeros((size, size, 4), dtype=np.uint8)
    dark[..., 3] = (np.clip((r - 0.75) / 0.25, 0, 1) * 60).astype(np.uint8)
    disc.alpha_composite(Image.fromarray(dark, "RGBA"))
    warn = []
    if logo is not None:
        # Fit so the logo's diagonal stays inside the 365px circle (max), aiming for ~340px.
        diag = math.hypot(logo.width, logo.height)
        s = 340 / diag
        w, h = logo.width * s, logo.height * s
        if max(w, h) < 243 * 0.75:
            warn.append("logo is very wide/tall; it may look small in the round slot")
        lg = logo.resize((max(1, round(w)), max(1, round(h))), Image.LANCZOS)
        disc.alpha_composite(lg, (round((size - w) / 2), round((size - h) / 2)))
    else:
        warn.append("no logo provided")
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(disc, (0, 0), mask)
    return out, warn


# ---------------------------------------------------------------- encoding
def encode(img, fmt, max_kb=None):
    buf = io.BytesIO()
    if fmt == "png":
        img.save(buf, "PNG", optimize=True)
        for colors in (256, 128, 64, 32):
            if not max_kb or buf.tell() / 1024 <= max_kb:
                break
            buf = io.BytesIO()
            img.quantize(colors=colors, method=Image.Quantize.FASTOCTREE).save(buf, "PNG", optimize=True)
        return buf.getvalue(), None
    rgbimg = img.convert("RGB")
    q = 92
    while True:
        buf = io.BytesIO()
        rgbimg.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
        if not max_kb or buf.tell() / 1024 <= max_kb or q <= 40:
            return buf.getvalue(), q
        q -= 7


def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "banner").lower()).strip("-")
    return s[:40] or "banner"


# ---------------------------------------------------------------- main
def run(job):
    base = os.path.dirname(os.path.abspath(job.get("_path", ".")))
    rel = lambda p: p if os.path.isabs(p) else os.path.join(base, p)
    with open(os.path.join(HERE, "placements.json"), encoding="utf-8") as f:
        catalog = json.load(f)["placements"]
    wanted = job.get("placements", "all")
    chosen = catalog if wanted == "all" else [p for p in catalog if p["id"] in wanted]
    missing = [] if wanted == "all" else [w for w in wanted if w not in {p["id"] for p in catalog}]
    arts = [Image.open(rel(p)).convert("RGB") for p in job["art"]]
    copy = job.get("copy", {})
    brand = job.get("brand", {})
    colors = {"background": "#101828", "primary": "#1d4ed8", "accent": "#ff5a1f", "text": "#ffffff", "ctaText": "#ffffff"}
    colors.update(brand.get("colors", {}))
    logo = Image.open(rel(brand["logo"])).convert("RGBA") if brand.get("logo") else None
    rtl = bool(RTL_RE.search(" ".join(copy.values())))
    name = slug(job.get("name"))
    out = rel(job.get("out", "output"))
    os.makedirs(out, exist_ok=True)
    results, previews = [], []
    for p in chosen:
        pcolors = dict(colors, **p.get("brand", {}).get("colors", {}))
        plogo = None if p.get("noLogo") else logo
        for s in p["sizes"]:
            W, H = s["width"], s["height"]
            fmt = (s.get("formats") or ["png"])[0]
            if s.get("kind") == "round-logo":
                img, warns = render_round_logo(logo, brand.get("logo_bg") or pcolors.get("primary") or pcolors["background"], W)
                data, q = encode(img, "png")
                fname = f"{p['id']}/{name}_logo_round.png"
            else:
                logo_only = s.get("logoOnly") and plogo is not None
                art_only = (not logo_only) and s.get("artOnly") and not job.get("text_on_image_only_slots")
                lay = compute_layout(W, H, rtl, art_only, s.get("safeZone"))
                if logo_only:
                    img = Image.new("RGBA", (W, H), rgb(pcolors["background"]) + (255,))
                    paste_logo(img, plogo, W * 0.15, H * 0.15, W * 0.7, H * 0.7, "center")
                    warns = []
                else:
                    _, _, aw, ah = (round(v) for v in lay["art"])
                    art = smart_crop(pick_art(arts, aw, ah), aw, ah)
                    if job.get("flip_art"):
                        art = art.transpose(Image.FLIP_LEFT_RIGHT)
                    img, warns = render_banner(W, H, art, plogo, pcolors, {} if art_only else copy, lay)
                    if art_only:
                        warns.append("image only: the platform shows the title/CTA")
                data, q = encode(img, fmt, s.get("maxKB"))
                ext = "jpg" if fmt == "jpg" else fmt
                sid = "" if s["id"] == f"{W}x{H}" else f"{s['id']}_"
                fname = f"{p['id']}/{name}_{p['id']}_{sid}{W}x{H}.{ext}"
            path = os.path.join(out, fname)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
            kb = round(len(data) / 1024)
            if s.get("maxKB") and kb > s["maxKB"]:
                warns.append(f"{kb} KB is over the {s['maxKB']} KB limit")
            results.append({"file": fname, "placement": p.get("name_fa") or p["name"], "slot": s.get("label_fa") or s.get("label") or s["id"], "size": f"{W}x{H}", "kb": kb, "warnings": warns})
            previews.append((fname, img))
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    zpath = os.path.join(os.path.dirname(out), f"{name}-banners.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for r in results:
            z.write(os.path.join(out, r["file"]), r["file"])
        z.write(os.path.join(out, "manifest.json"), "manifest.json")
    # contact sheet for showing in chat
    thumbs = []
    for _, im in previews:
        t = im.copy()
        t.thumbnail((360, 260))
        thumbs.append(t)
    cols = 4
    cw, rh = 380, 280
    rows = math.ceil(len(thumbs) / cols) or 1
    sheet = Image.new("RGB", (cols * cw, rows * rh), (236, 236, 240))
    for i, t in enumerate(thumbs):
        bgc = Image.new("RGBA", t.size, (200, 200, 205, 255))
        bgc.alpha_composite(t.convert("RGBA"))
        sheet.paste(bgc.convert("RGB"), ((i % cols) * cw + (cw - t.width) // 2, (i // cols) * rh + (rh - t.height) // 2))
    sheet.save(os.path.join(out, "preview.png"))
    return {"zip": zpath, "preview": os.path.join(out, "preview.png"), "count": len(results), "rtl": rtl, "raqm": RAQM, "unknown_placements": missing, "files": results}


if __name__ == "__main__":
    jp = sys.argv[1] if len(sys.argv) > 1 else "job.json"
    with open(jp, encoding="utf-8") as f:
        job = json.load(f)
    job["_path"] = jp
    print(json.dumps(run(job), ensure_ascii=False, indent=2))
