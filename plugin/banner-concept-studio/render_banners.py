#!/usr/bin/env python3
"""Banner Studio renderer (runs inside ChatGPT's Python tool).

Turns approved, text-free artwork + copy + brand into every size of the chosen
ad placements, with Persian (RTL) text, logo, CTA, file-size limits and a ZIP.

Usage:  python render_banners.py job.json
job.json:
{
  "name": "wallgold",                          # used for file names
  "art": ["landscape.png", "square.png", "portrait.png", "wide.png"],
  "copy": {"headline": "...", "sub": "...", "cta": "...", "highlight": "part of headline (optional)"},
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
U = 1  # render scale: every px rule below is in banner (1x) pixels times U
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
    words, lines, cur = [], [], ""
    for w in (text or "").split():
        if w == "و" and words:  # keep the Persian 'and' at the end of its line, never opening one
            words[-1] += " " + w
        else:
            words.append(w)
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



def down(img, size, box=None):
    """High-quality resize: LANCZOS, plus a light unsharp mask when shrinking a lot (keeps detail crisp)."""
    W, H = size
    bw = (box[2] - box[0]) if box else img.width
    bh = (box[3] - box[1]) if box else img.height
    out = img.resize((W, H), Image.LANCZOS, box=box)
    k = min(W / max(1, bw), H / max(1, bh))
    if k < 0.75:
        amt = int(min(90, 40 + (0.75 - k) * 80))
        if out.mode == "RGBA":
            a = out.getchannel("A")
            out = out.convert("RGB").filter(ImageFilter.UnsharpMask(0.8, amt, 2)).convert("RGBA")
            out.putalpha(a)
        else:
            out = out.filter(ImageFilter.UnsharpMask(0.8, amt, 2))
    return out

def fit(text, path, max_w, max_h, max_size, min_size, max_lines, lh=1.3):
    if not text:
        return None
    size = int(max_size)
    while size >= min_size:
        f = Text(path, size)
        lines = wrap(text, f, max_w)
        if len(lines) <= max_lines and max(f.width(l) for l in lines) <= max_w and len(lines) * size * lh <= max_h:
            if len(lines) > 1:  # balance the lines (no lonely last word)
                lo, hi_ = max(f.width(w) for w in wrap(text, f, 0)), max_w
                n = len(lines)
                for _ in range(12):
                    mid = (lo + hi_) / 2
                    if len(wrap(text, f, mid)) <= n:
                        hi_ = mid
                    else:
                        lo = mid
                lines = wrap(text, f, hi_ + 1)
            return {"font": f, "lines": lines, "size": size, "lh": lh, "height": len(lines) * size * lh}
        size -= max(1, round(size * 0.04))
    return None


def draw_block(draw, block, x, y, align, color, hi=None, hi_rects=None):
    """hi: phrase to emphasise; its on-screen spans are appended to hi_rects."""
    f = block["font"]
    for i, line in enumerate(block["lines"]):
        w = f.width(line)
        lx = x if align == "left" else x - w if align == "right" else x - w / 2
        ly = y + i * block["size"] * block["lh"]
        f.draw(draw, (lx, ly), line, color)
        if hi and hi_rects is not None and hi in line:
            k = line.index(hi)
            pre, ww = f.width(line[:k]), f.width(hi)
            rtl = bool(RTL_RE.search(line))
            x1 = lx + w - pre if rtl else lx + pre + ww
            t, kw = f.prep(line)
            _, by0, _, by1 = f.font.getbbox(t, **kw)
            pad_ = block["size"] * 0.08
            hi_rects.append((x1 - ww - 1, ly + by0 - pad_, x1 + 1, ly + by1 + pad_))


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
        wide = r > 5 and H >= 120 * U
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
    return down(img, (W, H), box=(sx, sy, sx + cw, sy + ch))


_SAL = {}


def anchor_crop(img, W, H, text_side):
    """Cover-crop that keeps the side opposite the copy (so the picture's own empty side lands under the text)."""
    img = img.convert("RGB")
    iw, ih = img.size
    s = max(W / iw, H / ih)
    cw, ch = min(iw, W / s), min(ih, H / s)
    if text_side == "right":
        sx, sy = 0.0, (ih - ch) / 2
    elif text_side == "left":
        sx, sy = iw - cw, (ih - ch) / 2
    else:  # copy at the bottom: keep the top
        sx, sy = (iw - cw) / 2, 0.0
    return down(img, (W, H), box=(sx, sy, sx + cw, sy + ch))


def plain_border(img, text_side):
    """Are the borders the picture would be extended past plain backdrop? (the side it is anchored to may be busy)"""
    a = np.asarray(img.convert("RGB").resize((64, 64), Image.BILINEAR), dtype=np.float32)
    parts = {"top": a[:3], "bottom": a[-3:], "left": a[:, :3], "right": a[:, -3:]}
    keep = {"right": "left", "left": "right", "bottom": "top"}.get(text_side)
    ring = np.concatenate([v.reshape(-1, 3) for k, v in parts.items() if k != keep])
    return float(ring.std(0).mean()) < 16


def pad_fit(img, W, H, text_side, zoom=1.0):
    """For pictures on a plain backdrop: fit the whole picture (zoomed out) and continue the plain
    backdrop around it. Seamless because the backdrop itself is plain; never used on busy edges."""
    img = img.convert("RGB")
    iw, ih = img.size
    s = min(W / iw, H / ih) * zoom
    w, h = max(2, round(iw * s)), max(2, round(ih * s))
    x = 0 if text_side == "right" else W - w if text_side == "left" else (W - w) // 2
    y = 0 if text_side == "bottom" else (H - h) // 2
    a = np.asarray(img.resize((w, h), Image.LANCZOS), dtype=np.float32)
    # continue the plain backdrop by replicating its own border, then soften it (no streaks: the border is plain)
    pad = np.pad(a, ((y, H - h - y), (x, W - w - x), (0, 0)), mode="edge")
    soft = np.asarray(Image.fromarray(pad.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(max(3, min(W, H) * 0.08))), dtype=np.float32)
    inside = np.zeros((H, W), dtype=np.float32)
    inside[y:y + h, x:x + w] = 1
    feather = max(2, min(w, h) * 0.04)
    mask = np.asarray(Image.fromarray((inside * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(feather)), dtype=np.float32)[..., None] / 255
    base = pad * mask + soft * (1 - mask)
    return Image.fromarray(base.clip(0, 255).astype(np.uint8), "RGB")


def pick_art(arts, w, h):
    """Closest aspect ratio; among similar ratios prefer the picture with more empty space."""
    t = math.log(w / h)

    def key(im):
        if id(im) not in _SAL:
            _SAL[id(im)] = float(saliency(im).mean())
        return (round(abs(math.log(im.width / im.height) - t) / 0.2), _SAL[id(im)])
    return min(arts, key=key)


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
        if tw + size * 1.6 <= max_w or size <= 8 * U:
            break
        size -= 1
    extra = h * 0.38 if h >= 26 * U else 0
    return f, math.ceil(min(max_w, tw + extra + max(h * 1.2, size * 1.8)))


def _lighten(hexc, k):
    r_ = np.array(rgb(hexc), dtype=np.float32)
    return tuple(int(v) for v in np.clip(r_ + (255 - r_) * k, 0, 255)) if k >= 0 else tuple(int(v) for v in np.clip(r_ * (1 + k), 0, 255))


def split_highlight(canvas, layer, tc, bg_hex, boxes, hi_rects, colors):
    if hi_rects:
        cands = [colors.get("accent"), colors.get("primary"), colors.get("background")]
        hc = next((c for c in cands if c and c.lower() != tc.lower() and contrast(c, bg_hex) >= 3), None)
        if hc:
            m = Image.new("L", layer.size, 0)
            dm = ImageDraw.Draw(m)
            for r in hi_rects:
                dm.rectangle(r, fill=255)
            a = layer.getchannel("A")
            hi_layer = layer.copy()
            hi_layer.putalpha(Image.fromarray((np.asarray(a, dtype=np.uint16) * np.asarray(m) // 255).astype(np.uint8)))
            layer.putalpha(Image.fromarray((np.asarray(a, dtype=np.uint16) * (255 - np.asarray(m)) // 255).astype(np.uint8)))
            compose_text(canvas, layer, tc, bg_hex, boxes)
            compose_text(canvas, hi_layer, hc, bg_hex, boxes)
            return
    compose_text(canvas, layer, tc, bg_hex, boxes)


def compose_text(canvas, layer, tc, bg_hex, boxes):
    """Make typed text look designed: tonal gradient fill, soft shadow in the scene's own hue,
    and a light print-blend so the scene texture shows through slightly."""
    W, H = canvas.size
    alpha = layer.getchannel("A")
    dark_text = lum(tc) < 0.35
    # 1. shadow / glow tinted from the background, not black
    bgv = np.array(rgb(bg_hex), dtype=np.float32)
    sh_col = tuple(int(v) for v in (bgv * 0.35)) if not dark_text else tuple(int(v) for v in (bgv * 0.7))
    for (x, y, w, h, size) in boxes:
        pass
    sz = max((b[4] for b in boxes), default=20)
    sh = Image.new("RGBA", (W, H), sh_col + (0,))
    off = max(1, round(sz * 0.05))
    a2 = Image.new("L", (W, H), 0)
    a2.paste(alpha, (0, off))
    a2 = a2.filter(ImageFilter.GaussianBlur(max(1, sz * (0.10 if dark_text else 0.14))))
    a2 = a2.point(lambda v: int(v * (0.35 if dark_text else 0.6)))
    sh.putalpha(a2)
    canvas.alpha_composite(sh)
    # 2. vertical tonal gradient per text block (lighter top -> base colour bottom)
    fill = Image.new("RGB", (W, H), rgb(tc))
    fa = np.asarray(fill, dtype=np.float32).copy()
    top_col = np.array(_lighten(tc, 0.22) if dark_text else _lighten(tc, -0.0), dtype=np.float32)
    base = np.array(rgb(tc), dtype=np.float32)
    bot_col = base if dark_text else np.array(_lighten(tc, -0.10), dtype=np.float32)
    for (x, y, w, h, size) in boxes:
        y0, y1 = max(0, int(y)), min(H, int(y + h) + 1)
        if y1 <= y0:
            continue
        t = np.linspace(0, 1, y1 - y0, dtype=np.float32)[:, None, None]
        fa[y0:y1, :, :] = top_col * (1 - t) + bot_col * t
    styled = Image.fromarray(fa.clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")
    styled.putalpha(alpha)
    # 3. print-blend: a touch of multiply (dark text) / screen (light text) with the scene
    under = np.asarray(canvas.convert("RGB"), dtype=np.float32)
    sv = np.asarray(styled.convert("RGB"), dtype=np.float32)
    blended = under * sv / 255 if dark_text else 255 - (255 - under) * (255 - sv) / 255
    mix = sv * 0.8 + blended * 0.2
    out = Image.fromarray(mix.clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")
    out.putalpha(alpha)
    canvas.alpha_composite(out)


def draw_cta(canvas, label, x, y, h, w, font, colors, rtl=True):
    acc = colors["accent"]
    r = h / 2
    W, H = canvas.size
    shc = tuple(int(v * 0.45) for v in rgb(acc))
    sh = Image.new("RGBA", canvas.size, shc + (0,))
    m = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((x, y + h * 0.14, x + w, y + h + h * 0.14), radius=r, fill=110)
    sh.putalpha(m.filter(ImageFilter.GaussianBlur(max(1, h * 0.22))))
    canvas.alpha_composite(sh)
    # gradient body
    x0, y0, x1, y1 = int(x), int(y), int(math.ceil(x + w)), int(math.ceil(y + h))
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    top, bot = np.array(_lighten(acc, 0.18), dtype=np.float32), np.array(_lighten(acc, -0.12), dtype=np.float32)
    t = np.linspace(0, 1, bh, dtype=np.float32)[:, None, None]
    body = np.broadcast_to(top * (1 - t) + bot * t, (bh, bw, 3)).astype(np.uint8)
    pill = Image.fromarray(np.ascontiguousarray(body), "RGB").convert("RGBA")
    pm = Image.new("L", (bw * 4, bh * 4), 0)
    ImageDraw.Draw(pm).rounded_rectangle((0, 0, bw * 4 - 1, bh * 4 - 1), radius=r * 4, fill=255)
    pm = pm.resize((bw, bh), Image.LANCZOS)
    pill.putalpha(pm)
    # inner top highlight
    hl = Image.new("RGBA", (bw, bh), (255, 255, 255, 0))
    hm = Image.new("L", (bw * 4, bh * 4), 0)
    ImageDraw.Draw(hm).rounded_rectangle((bw * 0.3, bh * 0.25, bw * 3.7, bh * 1.9), radius=r * 2, fill=255)
    hm = hm.resize((bw, bh), Image.LANCZOS).filter(ImageFilter.GaussianBlur(max(1, bh * 0.08)))
    hl.putalpha(hm.point(lambda v: int(v * 0.16)))
    pill.alpha_composite(hl)
    canvas.alpha_composite(pill, (x0, y0))
    d = ImageDraw.Draw(canvas)
    col = readable(colors.get("ctaText"), acc)
    arrow = h >= 26 * U and font.width(label) + h * 0.38 + h * 0.9 <= w
    aw_ = h * 0.22 if arrow else 0
    gap = h * 0.16 if arrow else 0
    tw = font.width(label)
    total = tw + (aw_ + gap if arrow else 0)
    sx = x + w / 2 - total / 2
    if arrow:
        # chevron points in reading direction (left for Persian)
        cy_ = y + h / 2
        ax0 = sx if rtl else sx + tw + gap
        tx = sx + aw_ + gap if rtl else sx
        lw = max(1, round(h * 0.07))
        if rtl:
            pts = [(ax0 + aw_ * 0.75, cy_ - aw_ * 0.6), (ax0 + aw_ * 0.15, cy_), (ax0 + aw_ * 0.75, cy_ + aw_ * 0.6)]
        else:
            pts = [(ax0 + aw_ * 0.25, cy_ - aw_ * 0.6), (ax0 + aw_ * 0.85, cy_), (ax0 + aw_ * 0.25, cy_ + aw_ * 0.6)]
        d.line(pts, fill=col, width=lw, joint="curve")
    else:
        tx = sx
    font.draw(d, (tx, y + h / 2), label, col, anchor="lm")



# ---------------------------------------------------------------- blending (infuse copy into the art)
def extend_art(art, W, H, box, axis):
    """Place art in box and continue its own edge colours across the rest of the canvas,
    with a wide feathered seam, so there is no hard panel edge or flat colour block."""
    ax, ay, aw, ah = box
    canvas = Image.new("RGB", (W, H))
    far_left = axis == "x" and ax > 0  # art on the right: continue its left edge leftwards
    # low-frequency colour field: edge colours in a few soft bands, fading into the scene's overall tone
    if axis == "x":
        e = max(2, round(aw * 0.12))
        edge = art.crop((0, 0, e, ah)) if far_left else art.crop((aw - e, 0, aw, ah))
        bands = edge.resize((1, 5), Image.BOX).resize((W, H), Image.BICUBIC)
    else:
        e = max(2, round(ah * 0.12))
        edge = art.crop((0, ah - e, aw, ah))
        bands = edge.resize((5, 1), Image.BOX).resize((W, H), Image.BICUBIC)
    glob_ = art.resize((3, 2), Image.BOX).resize((W, H), Image.BICUBIC)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    if axis == "x":
        dist = ((ax - xx) if far_left else (xx - ax - aw)) / max(1, W - aw)
    else:
        dist = (yy - ay - ah) / max(1, H - ah)
    k = np.clip(dist, 0, 1)[..., None] * 0.55
    fill = np.asarray(bands, dtype=np.float32) * (1 - k) + np.asarray(glob_, dtype=np.float32) * k
    fill = Image.fromarray(fill.clip(0, 255).astype(np.uint8), "RGB").filter(ImageFilter.GaussianBlur(max(4, min(W, H) * 0.2)))
    canvas.paste(fill)
    a = Image.new("RGB", (W, H))
    a.paste(art, (ax, ay))
    if axis == "x":
        feather = aw * 0.35
        d = (xx - ax) if far_left else (ax + aw - xx)
    else:
        feather = ah * 0.3
        d = ay + ah - yy
    m = np.clip(d / max(1, feather), 0, 1)
    m = m * m * (3 - 2 * m)
    mask = Image.fromarray((m * 255).astype(np.uint8), "L")
    canvas.paste(a, (0, 0), mask)
    return canvas


def busy_area(img, box):
    x, y, w, h = (max(0, round(v)) for v in box)
    r = img.convert("L").crop((x, y, x + max(1, w), y + max(1, h))).resize((32, 32), Image.BILINEAR)
    a = np.asarray(r, dtype=np.float32)
    edge = np.abs(np.diff(a, axis=0)).mean() + np.abs(np.diff(a, axis=1)).mean()
    return a.std() > 24 or edge > 9


def saliency(img, gw=120):
    """0..1 map of 'things' in the picture (subject, props), ignoring smooth backdrop and soft light."""
    iw, ih = img.size
    gh = max(8, round(ih * gw / iw))
    a = np.asarray(img.convert("RGB").resize((gw, gh), Image.BILINEAR), dtype=np.float32)
    b = np.asarray(img.convert("RGB").resize((gw, gh), Image.BILINEAR).filter(ImageFilter.GaussianBlur(gw * 0.12)), dtype=np.float32)
    l = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    ed = np.zeros_like(l)
    ed[:, 1:] += np.abs(np.diff(l, axis=1))
    ed[1:, :] += np.abs(np.diff(l, axis=0))
    local = np.sqrt(((a - b) ** 2).sum(2))          # differs from its smooth surroundings
    mx, mn = a.max(2), a.min(2)
    sat = (mx - mn) / np.maximum(mx, 1)
    border = np.concatenate([sat[0], sat[-1], sat[:, 0], sat[:, -1]])
    s = local / 40 + ed / 25 + np.maximum(0, sat - np.median(border) - 0.12) * 2.5
    s = np.asarray(Image.fromarray(np.clip(s * 120, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.5)), dtype=np.float32) / 255
    return s > 0.33


def fit_free(lay, img):
    """Shrink the copy area so it never covers the subject; if too little room is left, reflow."""
    if lay["mode"] != "full" or lay["side"] == "none":
        return lay
    W, H = lay["W"], lay["H"]
    m = saliency(img)
    gh, gw = m.shape
    side = lay["side"]
    nl = dict(lay)
    cx, cy, cw, ch = lay["content"]
    if side in ("left", "right"):
        col = m.mean(0)
        hot = col > 0.06
        rng = range(gw - 1, -1, -1) if side == "right" else range(gw)
        edge = None
        for i in rng:
            if hot[i]:
                edge = i
                break
        if edge is None:
            return nl
        margin = W * 0.03
        if side == "right":
            x0 = max(cx, (edge + 1) / gw * W + margin)
            nl["content"] = (x0, cy, W - x0, ch)
            free = W - x0
        else:
            x1 = min(cx + cw, edge / gw * W - margin)
            nl["content"] = (0, cy, x1, ch)
            free = x1
        if free < W * 0.3:
            return None
    else:
        row = m.mean(1)
        hot = row > 0.06
        edge = None
        for j in range(gh - 1, -1, -1):
            if hot[j]:
                edge = j
                break
        if edge is None:
            return nl
        y0 = max(cy, (edge + 1) / gh * H + H * 0.03)
        nl["content"] = (cx, y0, cw, H - y0)
        if H - y0 < H * 0.3:
            return None
    return nl


def card_canvas(src, W, H, box):
    """Clean fallback when the picture has no empty space: the whole picture, uncut, in a rounded
    card on one side, on a smooth deep gradient taken from the picture's own colours. No fading."""
    v = np.asarray(src.convert("RGB").resize((1, 1), Image.BOX), dtype=np.float32)[0, 0]
    mx = max(1.0, float(v.max()))
    c1 = v / mx * 62
    c2 = v / mx * 105
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    t = np.clip((xx / max(1, W) * 0.6 + yy / max(1, H) * 0.4), 0, 1)[..., None]
    bg = c2 * (1 - t) + c1 * t
    canvas = Image.fromarray(bg.clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")
    ax, ay, aw, ah = box
    m = max(3, round(min(W, H) * 0.06))
    bw, bh = max(4, aw - 2 * m), max(4, ah - 2 * m)
    s = min(bw / src.width, bh / src.height)
    cw, ch = max(2, round(src.width * s)), max(2, round(src.height * s))
    cx, cy = round(ax + (aw - cw) / 2), round(ay + (ah - ch) / 2)
    r = max(2, round(min(cw, ch) * 0.07))
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((cx, cy + m * 0.25, cx + cw, cy + ch + m * 0.25), radius=r, fill=(0, 0, 0, 110))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(max(2, m * 0.5))))
    card = down(src.convert("RGB"), (cw, ch)).convert("RGBA")
    mk = Image.new("L", (cw * 4, ch * 4), 0)
    ImageDraw.Draw(mk).rounded_rectangle((0, 0, cw * 4 - 1, ch * 4 - 1), radius=r * 4, fill=255)
    card.putalpha(mk.resize((cw, ch), Image.LANCZOS))
    canvas.alpha_composite(card, (cx, cy))
    return canvas


def reflow_layout(lay):
    """Full-bleed layout whose copy area would cover the subject -> art panel + extended background."""
    W, H, rtl, side = lay["W"], lay["H"], lay["rtl"], lay["side"]
    nl = dict(lay, reflowed=True)
    if side == "bottom" and W / H >= 1.0:
        side = "right" if rtl else "left"
    if side in ("left", "right"):
        aw = round(min(W * (0.44 if W / H < 1.4 else 0.5), H * 1.25))
        nl["art"] = (W - aw, 0, aw, H) if side == "left" else (0, 0, aw, H)
        nl["content"] = (0, 0, W - aw, H) if side == "left" else (aw, 0, W - aw, H)
        nl["mode"], nl["side"] = "strip", "none"
    else:
        ah = round(H * 0.56)
        nl["art"], nl["content"] = (0, 0, W, ah), (0, ah, W, H - ah)
        nl["mode"], nl["side"] = "tower", "none"
    return nl


def shift_bg(img, dx, dy=0):
    """Move the background by (dx, dy); the uncovered strip continues the plain edge (only used when that edge is plain)."""
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    H, W = a.shape[:2]
    dx, dy = int(round(dx)), int(round(dy))
    pad = np.pad(a, ((max(0, dy), max(0, -dy)), (max(0, dx), max(0, -dx)), (0, 0)), mode="edge")
    y0, x0 = max(0, -dy), max(0, -dx)
    out = pad[y0:y0 + H, x0:x0 + W]
    soft = np.asarray(Image.fromarray(out.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(max(2, min(W, H) * 0.05))), dtype=np.float32)
    m = np.zeros((H, W), dtype=np.float32)
    if dx > 0:
        m[:, :dx] = 1
    if dx < 0:
        m[:, W + dx:] = 1
    if dy > 0:
        m[:dy, :] = 1
    if dy < 0:
        m[H + dy:, :] = 1
    m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(max(1, min(W, H) * 0.02))), dtype=np.float32)[..., None] / 255
    return Image.fromarray((out * (1 - m) + soft * m).clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")


def plain_strip(img, side, frac=0.04):
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    H, W = a.shape[:2]
    k = max(2, int(W * frac)) if side in ("left", "right") else max(2, int(H * frac))
    part = {"left": a[:, :k], "right": a[:, W - k:], "top": a[:k], "bottom": a[H - k:]}[side]
    return float(part.reshape(-1, 3).std(0).mean()) < 14


def ink_box(before, after):
    d = np.abs(np.asarray(after.convert("RGB"), dtype=np.int16) - np.asarray(before.convert("RGB"), dtype=np.int16)).max(2) > 18
    ys, xs = np.where(d)
    if not len(xs):
        return None
    return xs.min(), ys.min(), xs.max(), ys.max()


def subject_box(img):
    m = saliency(img)
    gh, gw = m.shape
    H, W = img.size[1], img.size[0]
    cols = np.where(m.mean(0) > 0.06)[0]
    rows = np.where(m.mean(1) > 0.06)[0]
    if not len(cols) or not len(rows):
        return None
    return cols.min() / gw * W, rows.min() / gh * H, (cols.max() + 1) / gw * W, (rows.max() + 1) / gh * H


def tighten(W, H, art, logo, colors, copy, lay, img):
    """Second pass: pull element and copy together when a wide gap opens between them, so long banners
    are composed as one group instead of 'picture far left, text far right'."""
    if lay["mode"] == "art" or "_bg" not in lay:
        return None
    bg, tb = lay["_bg"], ink_box(lay["_pre_text"], img)
    sb = subject_box(bg)
    if tb is None or sb is None:
        return None
    horiz = lay["mode"] == "strip" or lay["side"] in ("left", "right")
    nl = {k: v for k, v in lay.items() if not k.startswith("_")}
    cx, cy, cw, ch = lay["content"]
    if horiz:
        text_right = tb[0] > sb[2] - 1
        gap = (tb[0] - sb[2]) if text_right else (sb[0] - tb[2])
        target = max(W * 0.05, H * 0.12)
        excess = gap - target
        if excess < W * 0.06:
            return None
        far = "left" if text_right else "right"
        de = excess * 0.5 if plain_strip(bg, far) else 0.0
        dt = excess - de
        sign = 1 if text_right else -1
        nl["pre_bg"] = shift_bg(bg, sign * de) if de else bg
        nl["content"] = (cx - sign * dt, cy, cw, ch)
    else:
        gap = tb[1] - sb[3]
        excess = gap - max(H * 0.04, 8 * U)
        if excess < H * 0.06:
            return None
        de = excess * 0.5 if plain_strip(bg, "top") else 0.0
        dt = excess - de
        nl["pre_bg"] = shift_bg(bg, 0, de) if de else bg
        nl["content"] = (cx, cy - dt, cw, ch + dt) if lay["mode"] == "tower" else (cx, cy - dt, cw, ch)
        if lay["mode"] == "full" and lay["side"] == "bottom":
            nl["content"] = (cx, cy - dt, cw, ch)
            nl["_bottom_pad"] = dt
    nl["pre_bg"] = nl["pre_bg"].convert("RGBA")
    return nl


def region_rgb(img, box):
    x, y, w, h = (max(0, round(v)) for v in box)
    r = img.convert("RGB").crop((x, y, max(x + 1, x + w), max(y + 1, y + h))).resize((24, 24), Image.BILINEAR)
    a = np.asarray(r, dtype=np.float32).reshape(-1, 3)
    return a.mean(0), float((a @ np.array([0.299, 0.587, 0.114])).std())


def hexof(v):
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, round(c)))) for c in v)


def pick_text(colors, bg_hex, busy):
    need = 4.5 if busy < 28 else 6
    cands = [colors.get("text"), colors.get("background"), colors.get("primary"), "#ffffff", "#141414"]
    for cnd in cands:
        if cnd and contrast(cnd, bg_hex) >= need:
            return cnd, False
    best = max(["#ffffff", "#141414"], key=lambda c: contrast(c, bg_hex))
    return best, True


# ---------------------------------------------------------------- element composition (plain-backdrop pictures)
def element_parts(src):
    """If the picture is a subject on a plain backdrop, return (backdrop field, element RGBA cutout)."""
    key = id(src)
    if key in _ELEM:
        return _ELEM[key]
    res = None
    img = src.convert("RGB")
    iw, ih = img.size
    sb = subject_box(img)
    if sb is not None:
        x0, y0, x1, y1 = sb
        mx, my = (x1 - x0) * 0.06, (y1 - y0) * 0.06
        x0, y0, x1, y1 = max(0, x0 - mx), max(0, y0 - my), min(iw, x1 + mx), min(ih, y1 + my)
        a = np.asarray(img, dtype=np.float32)
        outside = np.ones((ih, iw), bool)
        outside[int(y0):int(math.ceil(y1)), int(x0):int(math.ceil(x1))] = False
        cover = (x1 - x0) * (y1 - y0) / (iw * ih)
        # texture check at a fixed scale: the backdrop must be smooth (no sand, fabric, light rays)
        sm_ = np.asarray(img.convert("L").resize((256, max(8, round(256 * ih / iw))), Image.BILINEAR), dtype=np.float32)
        gy, gx = sm_.shape
        g_ = np.zeros_like(sm_)
        g_[:, 1:] += np.abs(np.diff(sm_, axis=1))
        g_[1:, :] += np.abs(np.diff(sm_, axis=0))
        o_ = np.ones_like(sm_, dtype=bool)
        o_[int(y0 / ih * gy):int(math.ceil(y1 / ih * gy)), int(x0 / iw * gx):int(math.ceil(x1 / iw * gx))] = False
        smooth = o_.any() and float(g_[o_].mean()) < 1.2
        if smooth and outside.sum() > iw * ih * 0.2 and cover < 0.75:
            # backdrop model: per-row mean of backdrop pixels, plus residual noise check
            rows = np.array([a[r][outside[r]].mean(0) if outside[r].any() else np.full(3, np.nan) for r in range(ih)])
            ok = ~np.isnan(rows[:, 0])
            if ok.sum() > ih * 0.3:
                idx = np.arange(ih)
                for c_ in range(3):
                    rows[:, c_] = np.interp(idx, idx[ok], rows[ok, c_])
                resid = (a - rows[:, None, :])[outside]
                _RES[key] = float(resid.std(0).mean())
                if _RES[key] < 12:
                    field = np.repeat(rows[:, None, :], 8, axis=1)
                    field = Image.fromarray(field.clip(0, 255).astype(np.uint8), "RGB")
                    crop = img.crop((int(x0), int(y0), int(math.ceil(x1)), int(math.ceil(y1))))
                    ca = np.asarray(crop, dtype=np.float32)
                    br = rows[int(y0):int(y0) + ca.shape[0]][:, None, :]
                    dist = np.sqrt(((ca - br) ** 2).sum(2))
                    al = np.clip((dist - 8) / 26, 0, 1)
                    # keep only real objects (detail), not soft light/rays that differ in colour
                    sm = saliency(img).astype(np.uint8) * 255
                    smi = Image.fromarray(sm, "L").resize((iw, ih), Image.BILINEAR).crop((int(x0), int(y0), int(math.ceil(x1)), int(math.ceil(y1))))
                    smi = smi.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(max(2, min(ca.shape[:2]) * 0.03)))
                    al = al * np.clip(np.asarray(smi, dtype=np.float32) / 255 * 1.6, 0, 1)
                    am = np.asarray(Image.fromarray((al * 255).astype(np.uint8), "L").filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(1.5)), dtype=np.float32) / 255
                    # fade out towards the crop's edges (except where the picture itself ends) so no box shows
                    hh_, ww_ = am.shape
                    fy, fx = np.mgrid[0:hh_, 0:ww_].astype(np.float32)
                    f = max(3.0, min(hh_, ww_) * 0.08)
                    dl = fx + (1e6 if x0 <= 0 else 0)
                    dr = (ww_ - 1 - fx) + (1e6 if x1 >= iw else 0)
                    dt = fy + (1e6 if y0 <= 0 else 0)
                    db = (hh_ - 1 - fy) + (1e6 if y1 >= ih else 0)
                    am = am * np.clip(np.minimum.reduce([dl, dr, dt, db]) / f, 0, 1)
                    am = Image.fromarray((am * 255).astype(np.uint8), "L")
                    el = crop.convert("RGBA")
                    el.putalpha(am)
                    res = (field, el)
    _ELEM[key] = res
    return res


def key_backdrop(img):
    """Cut a subject off a plain backdrop: alpha from the distance to the border colour (row by row)."""
    a = np.asarray(img, dtype=np.float32)
    h, w = a.shape[:2]
    k = max(2, round(min(w, h) * 0.03))
    edge = np.concatenate([a[:, :k], a[:, w - k:]], axis=1)
    rows = np.median(edge, axis=1)
    dist = np.sqrt(((a - rows[:, None, :]) ** 2).sum(2))
    al = np.clip((dist - 10) / 28, 0, 1)
    am = Image.fromarray((al * 255).astype(np.uint8), "L").filter(ImageFilter.MedianFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    out = img.convert("RGBA")
    out.putalpha(am)
    bb = am.point(lambda v: 255 if v > 40 else 0).getbbox()
    return out.crop(bb) if bb else out


_ELEM = {}
_RES = {}


def element_layout(W, H, rtl, el, field, text_w=None):
    """Arrange element + copy as one group for this exact size. Returns (background, layout)."""
    r = W / H
    canvas = field.resize((W, H), Image.BICUBIC).convert("RGBA")
    ew_, eh_ = el.size
    m = max(4, round(min(W, H) * 0.06))
    if r >= 1.0:  # side by side
        if r >= 2.6:
            eh = H * (0.9 if H < 130 * U else 0.84)
            maxw = W * 0.3
        elif r >= 1.4:
            eh, maxw = H * 0.74, W * 0.4
        else:
            eh, maxw = H * 0.6, W * 0.4
        s = min(eh / eh_, maxw / ew_)
        w, h = ew_ * s, eh_ * s
        gap = max(m * 0.8, W * 0.035)
        free = W - 2 * m - w - gap
        tw = min(free, text_w) if text_w else free
        cluster = w + gap + tw
        x0 = (W - cluster) / 2
        ex = x0 if rtl else x0 + tw + gap
        tx = ex + w + gap if rtl else x0
        ey = (H - h) / 2
        lay = dict(mode="strip", side="none", art=(ex, ey, w, h), content=(tx - m * 0.5, 0, tw + m, H), W=W, H=H, rtl=rtl, reflowed=r < 2.6)
    else:  # stacked: element on top, copy below
        eh = H * (0.42 if r < 0.5 else 0.5)
        s = min(eh / eh_, W * 0.86 / ew_)
        w, h = ew_ * s, eh_ * s
        gap = max(m * 0.6, H * 0.03)
        th = min(H - 2 * m - h - gap, text_w) if text_w else H - 2 * m - h - gap
        cluster = h + gap + th
        y0 = (H - cluster) / 2
        ex, ey = (W - w) / 2, y0
        lay = dict(mode="tower", side="none", art=(ex, ey, w, h), content=(0, ey + h + gap - m * 0.5, W, th + m), W=W, H=H, rtl=rtl, reflowed=True)
    lay["_small"] = r < 1.0 and h < H * 0.25
    elr = down(el, (max(1, round(w)), max(1, round(h))))
    canvas.alpha_composite(elr, (round(ex), round(ey)))
    lay["pre_bg"] = canvas
    lay["style"] = "blend"
    return lay


# ---------------------------------------------------------------- banner
def render_banner(W, H, art, logo, colors, copy, layout):
    c = dict(colors)
    if contrast(c["accent"], c["background"]) < 1.8:
        c["accent"] = c["primary"] if contrast(c.get("primary", "#000"), c["background"]) >= 1.8 else readable(None, c["background"])
    mode, side, rtl = layout["mode"], layout["side"], layout["rtl"]
    ax, ay, aw, ah = (round(v) for v in layout["art"])
    warnings = []
    blend = layout.get("style", "blend") == "blend"
    if layout.get("pre_bg") is not None:
        canvas = layout["pre_bg"].convert("RGBA").copy()
    elif art is not None and layout.get("card"):
        canvas = art.convert("RGBA")
    elif art is not None and blend and mode in ("strip", "tower"):
        canvas = extend_art(art, W, H, (ax, ay, aw, ah), "x" if mode == "strip" else "y").convert("RGBA")
    else:
        canvas = Image.new("RGBA", (W, H), rgb(c["background"]) + (255,))
        if art is not None:
            canvas.alpha_composite(art.convert("RGBA"), (ax, ay))
    if mode == "art":
        return canvas, warnings
    layout["_bg"] = canvas.copy()
    bg = c["background"]
    if blend:
        reg, busy = region_rgb(canvas, layout["content"])
        bg = hexof(reg)
        tc, need_scrim = pick_text(c, bg, busy)
        if layout.get("scrim"):
            tc, need_scrim = (c.get("text") if c.get("text") and lum(c["text"]) > 0.6 else "#ffffff"), True
        # CTA: brand accent if it stands out on this area, else a brand colour that does, else text colour
        for cand in (colors.get("accent"), colors.get("primary"), colors.get("background"), tc):
            if cand and contrast(cand, bg) >= 2.2:
                c["accent"] = cand
                break
        if need_scrim and layout.get("scrim"):
            v = np.array(reg, dtype=np.float32)
            mx_ = max(1.0, float(v.max()))
            deep = hexof(v / mx_ * 70)  # same hue, deep value
            cx_, cy_, cw_, ch_ = layout["content"]
            if side == "right":
                canvas.alpha_composite(gradient(W, H, cx_, 0, cx_ - W * 0.28, 0, deep, 0.84, 0.0))
            elif side == "left":
                canvas.alpha_composite(gradient(W, H, cx_ + cw_, 0, cx_ + cw_ + W * 0.28, 0, deep, 0.84, 0.0))
            else:
                canvas.alpha_composite(gradient(W, H, 0, cy_, 0, cy_ - H * 0.25, deep, 0.86, 0.0))
            reg, _ = region_rgb(canvas, layout["content"])
            bg = hexof(reg)
        elif need_scrim:
            # a soft veil of the area's own colour pushed away from the text colour (no flat brand block)
            shade = reg * (1.25 if lum(tc) < 0.4 else 0.45)
            shade = hexof(np.minimum(255, shade + (40 if lum(tc) < 0.4 else 0)))
            cx_, cy_, cw_, ch_ = layout["content"]
            if mode == "full" and side in ("left", "right"):
                canvas.alpha_composite(gradient(W, H, 0 if side == "left" else W, 0, W * 0.65 if side == "left" else W * 0.35, 0, shade, 0.7, 0.0))
            elif mode == "full":
                canvas.alpha_composite(gradient(W, H, 0, H, 0, H * 0.45, shade, 0.75, 0.0))
            else:
                veil = Image.new("RGBA", (W, H), rgb(shade) + (0,))
                vm = Image.new("L", (W, H), 0)
                ImageDraw.Draw(vm).rectangle((cx_, cy_, cx_ + cw_, cy_ + ch_), fill=150)
                veil.putalpha(vm.filter(ImageFilter.GaussianBlur(max(4, min(W, H) * 0.25))))
                canvas.alpha_composite(veil)
            reg, _ = region_rgb(canvas, layout["content"])
            bg = hexof(reg)
            tc = max(["#ffffff", "#141414", tc], key=lambda t: contrast(t, bg)) if contrast(tc, bg) < 4.5 else tc
    else:
        if mode == "full" and side in ("left", "right"):
            canvas.alpha_composite(gradient(W, H, 0 if side == "left" else W, 0, W * 0.7 if side == "left" else W * 0.3, 0, bg, 0.88, 0.0))
        elif mode == "full":
            canvas.alpha_composite(gradient(W, H, 0, H, 0, H * 0.4, bg, 0.92, 0.0))
        elif mode == "strip":
            bw = aw * 0.45
            x0 = ax + aw if rtl else ax
            canvas.alpha_composite(gradient(W, H, x0, 0, x0 - bw if rtl else x0 + bw, 0, bg, 1.0, 0.0))
        elif mode == "tower":
            canvas.alpha_composite(gradient(W, H, 0, ah, 0, ah * 0.7, bg, 1.0, 0.0))
        tc = None

    tc = tc or readable(c.get("text"), bg)
    layout["_pre_text"] = canvas.copy()
    tl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(tl)
    tl_boxes = []
    hi = (copy.get("highlight") or "").strip() or None
    hi_rects = []
    headline, sub, cta = copy.get("headline", ""), copy.get("sub", ""), copy.get("cta", "")
    md = min(W, H)
    pad = max(6 * U, round(md * 0.07))
    cx, cy, cw, chh = layout["content"]
    box = (cx + pad, cy + pad, cw - 2 * pad, chh - 2 * pad)
    start = "right" if rtl else "left"

    # inline row for short strips (728×90, 468×60, 1081×144 ...)
    if mode == "strip" and H < 130 * U:
        bx, by, bw_, bh = box
        X = (lambda dist, w=0: bx + bw_ - dist - w) if rtl else (lambda dist, w=0: bx + dist)
        dist = 0
        if logo is not None:
            lh = H * 0.42
            lw = min(bw_ * 0.18, logo.width / logo.height * lh)
            paste_logo(canvas, logo, X(dist, lw), (H - lh) / 2, lw, lh, start)
            dist += lw + pad
        ctaw, f, ch = 0, None, 0
        if cta:
            ch = round(max(18 * U, H * 0.4))
            f, ctaw = cta_size(cta, ch, bw_ * 0.38)
        tw = bw_ - ctaw - pad - dist
        two = H >= 70 * U and sub
        c1 = fit(headline, FONT_HEAD, tw, (0.6 if two else 1) * bh, bh * (0.5 if two else 0.62), 9 * U, 1, 1.25)
        c2 = fit(headline, FONT_HEAD, tw, (0.6 if two else 1) * bh, bh * (0.5 if two else 0.62), 9 * U, 2, 1.2)
        head = max([x for x in (c1, c2) if x], key=lambda x: x["size"] * (1.15 if len(x["lines"]) == 1 else 1), default=None)
        sb = fit(sub, FONT_BODY, tw, bh - head["height"] - 2, head["size"] * 0.6, 9 * U, 1, 1.3) if (two and head) else None
        if not head:
            warnings.append("headline too long for this size")
            if cta:
                draw_cta(canvas, cta, X(bw_ - ctaw, ctaw), (H - ch) / 2, ch, ctaw, f, c, rtl)
        else:
            total = head["height"] + (sb["height"] + 2 if sb else 0)
            y = (H - total) / 2
            tx = bx + bw_ - dist if rtl else bx + dist
            draw_block(d, head, tx, y, start, tc, hi, hi_rects)
            tl_boxes.append((0, y, W, head["height"], head["size"]))
            used = max(head["font"].width(l) for l in head["lines"])
            if sb:
                draw_block(d, sb, tx, y + head["height"] + 2, start, tc)
                tl_boxes.append((0, y + head["height"] + 2, W, sb["height"], sb["size"]))
                used = max(used, max(sb["font"].width(l) for l in sb["lines"]))
            elif sub:
                warnings.append("subtext dropped (no room)")
            if cta:
                draw_cta(canvas, cta, X(dist + used + pad * 1.4, ctaw), (H - ch) / 2, ch, ctaw, f, c, rtl)
            split_highlight(canvas, tl, tc, bg, tl_boxes, hi_rects, colors)
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
    sm = "full" if layout.get("reflowed") else mode
    ch = round(min(max(md * (0.2 if sm == "strip" else 0.11), 22 * U), avail * 0.22)) if cta else 0
    gap = round(max(4 * U, avail * 0.04))
    text_h = avail - (ch + gap * 1.6 if cta else 0)
    head_max = min(bw_ * 0.12, text_h * 0.5) if sm == "strip" else min(md * 0.15, text_h * 0.5)
    head, sb = None, None
    asp = bw_ / max(1, text_h)
    pref = 1 if asp >= 3.2 else 2 if asp >= 1.5 else 3  # wide copy areas read in fewer, longer lines
    for lines in sorted({pref, 3}):
        share = 0.62 if sub else 1
        for tries in range(4):
            head = fit(headline, FONT_HEAD, bw_, text_h * share, head_max * (1 - tries * 0.12), 10 * U, lines, 1.18)
            if not head or not sub:
                break
            sb = fit(sub, FONT_BODY, bw_, text_h - head["height"] - gap, max(10 * U, head["size"] * 0.4), max(9 * U, round(md * 0.03)), min(3, lines + 1), 1.5)
            if sb:
                break
            share -= 0.08
        if head and (sb or not sub) and head["size"] >= head_max * 0.55:
            break
    if head and sub and not sb:
        warnings.append("subtext dropped (no room)")
    if not head and headline:
        warnings.append("headline too long for this size")
    block_h = (head["height"] if head else 0) + (gap + sb["height"] if sb else 0) + (gap * 1.6 + ch if cta else 0)
    y = top + avail - block_h if (mode == "full" and side == "bottom") else top + (avail - block_h) / 2
    if head:
        draw_block(d, head, axx, y, align, tc, hi, hi_rects)
        tl_boxes.append((0, y, W, head["height"], head["size"]))
        y += head["height"]
    if sb:
        y += gap
        draw_block(d, sb, axx, y, align, tc)
        tl_boxes.append((0, y, W, sb["height"], sb["size"]))
        y += sb["height"]
    if cta:
        y += gap * 1.6
        f, w = cta_size(cta, ch, bw_)
        x = bx if align == "left" else bx + bw_ - w if align == "right" else bx + (bw_ - w) / 2
        draw_cta(canvas, cta, x, y, ch, w, f, c, rtl)
    if tl_boxes:
        split_highlight(canvas, tl, tc, bg, tl_boxes, hi_rects, colors)
    return canvas, warnings


def _blur(a, r):
    if r <= 0:
        return a
    im = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8), "L")
    return np.asarray(im.filter(ImageFilter.GaussianBlur(r)), dtype=np.float32) / 255


def _overlay(b, s):
    return np.where(b < 0.5, 2 * b * s, 1 - 2 * (1 - b) * (1 - s))


def _inner_shadow(alpha, size, choke=0.0):
    """Photoshop-like inner shadow amount (0..1) for distance 0: strongest at the shape's edge."""
    r = max(1.0, size / 3.0)
    inv = _blur(1 - alpha, r)
    amt = np.clip(inv * (1 + choke / 100 * 2) * 1.4, 0, 1)
    return amt * alpha


def menchers_file2(logo, bg_hex, size=512):
    """Menchers kit 'file 2': brand-colour square, logo centred inside the 365px circle (min 243px)."""
    f2 = Image.new("RGBA", (size, size), rgb(bg_hex) + (255,))
    warn = []
    if logo is None:
        warn.append("no logo provided")
        return f2, warn
    bb = logo.getchannel("A").getbbox() if logo.mode == "RGBA" else None
    lg = logo.crop(bb) if bb else logo
    diag = math.hypot(lg.width, lg.height)
    s = 365 * 0.97 / diag  # whole logo stays inside the 365px circle
    w, h = lg.width * s, lg.height * s
    if max(w, h) < 243:  # very wide/tall logo: grow to the 243px minimum along its long side if it still fits
        s2 = 243 / max(lg.width, lg.height)
        if math.hypot(lg.width * s2, lg.height * s2) <= 365:
            s, w, h = s2, lg.width * s2, lg.height * s2
        else:
            warn.append("logo is very wide/tall; it is smaller than the 243px minimum")
    lg = lg.resize((max(1, round(w)), max(1, round(h))), Image.LANCZOS)
    f2.alpha_composite(lg, (round(256.5 - w / 2), round(256.5 - h / 2)))
    return f2, warn


FONT_DISPLAY = os.path.join(HERE, "fonts", "Lalezar-Regular.ttf")


def _sticker_text(text, max_w, max_h, fill, stroke_in, stroke_out, size_max=120, n_lines=None):
    """Heavy display headline with layered strokes + 3D drop, as an RGBA tile.
    n_lines: force (about) that many lines, tightly leaded, at size_max."""
    path = FONT_DISPLAY if os.path.exists(FONT_DISPLAY) else FONT_HEAD
    blk = None
    if n_lines:
        f0 = Text(path, int(size_max))
        longest = max(f0.width(w) for w in wrap(text, f0, 0))
        for k_ in (1.08, 1.2, 1.35, 1.5):
            mw = max(longest, f0.width(text) / n_lines * k_)
            blk = fit(text, path, mw, 10 ** 5, size_max, 20, n_lines, 0.92)
            if blk and len(blk["lines"]) == n_lines:
                break
        else:
            return None
    for lines in (() if n_lines else (2, 1, 3)):
        b_ = fit(text, path, max_w * 0.86, max_h * 0.86, size_max, 20, lines, 0.98)
        if b_ and (blk is None or b_["size"] > blk["size"] * 1.08):
            blk = b_
    if not blk:
        return None
    f, sz = blk["font"], blk["size"]
    so, si = max(2, round(sz * 0.11)), max(2, round(sz * 0.065))
    depth = max(2, round(sz * 0.07))
    W_ = int(max(f.width(l) for l in blk["lines"]) + 2 * so + 8)
    H_ = int(blk["height"] + sz * 0.6 + 2 * so + depth + 8)
    layer = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))

    def draw_all(dr, dy, col, stroke, scol):
        for i, line in enumerate(blk["lines"]):
            t, kw = f.prep(line)
            w = f.width(line)
            dr.text((W_ / 2 - w / 2, so + 4 + dy + i * sz * blk["lh"]), t, font=f.font, fill=col,
                    stroke_width=stroke, stroke_fill=scol, **kw)
    dr = ImageDraw.Draw(layer)
    # soft shadow
    sh = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
    draw_all(ImageDraw.Draw(sh), depth + sz * 0.05, (0, 0, 0, 120), so, (0, 0, 0, 120))
    layer.alpha_composite(sh.filter(ImageFilter.GaussianBlur(max(2, sz * 0.06))))
    # 3D extrusion in the outer stroke colour, darker
    ext = tuple(int(v * 0.6) for v in stroke_out)
    for k in range(depth, 0, -1):
        draw_all(dr, k, ext, so, ext)
    draw_all(dr, 0, stroke_out, so, stroke_out)
    if stroke_in:
        draw_all(dr, 0, stroke_in, si, stroke_in)
    # fill with a gentle vertical gradient
    fl = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
    draw_all(ImageDraw.Draw(fl), 0, (255, 255, 255, 255), 0, None)
    top = np.array(_lighten(hexof(fill), 0.12), dtype=np.float32)
    bot = np.array(_lighten(hexof(fill), -0.12), dtype=np.float32)
    t_ = np.linspace(0, 1, H_, dtype=np.float32)[:, None, None]
    grad = np.broadcast_to(top * (1 - t_) + bot * t_, (H_, W_, 3)).astype(np.uint8)
    g = Image.fromarray(np.ascontiguousarray(grad), "RGB").convert("RGBA")
    g.putalpha(fl.getchannel("A"))
    layer.alpha_composite(g)
    return layer


def _fits_circle(tile, x, y, cx, cy, R):
    a = np.asarray(tile.getchannel("A"))
    ys, xs = np.where(a > 40)
    if not len(xs):
        return True
    d = np.sqrt((xs + x - cx) ** 2 + (ys + y - cy) ** 2)
    return float(d.max()) <= R


def menchers_element_file2(element, text, bg_hex, colors, size=512, layout="stack"):
    """Menchers 'file 2' in the campaign style: a big sticker-style headline over the ad's element, on the
    brand colour with a soft spotlight. Sized like the campaign tokens: headline and element go out to the
    visible disc (file 1 shows file 2 through a 511px circle whose centre is at y 296.5 here, cut at y 454),
    keeping a ~30px margin from its rim and the bottom cut."""
    cx, cy, R = 256.5, 296.5, 226.0
    BOT = 446  # bottom cut of the visible disc (454) minus a margin
    base = np.array(rgb(bg_hex), dtype=np.float32)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    rr = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / 300
    light = np.clip(1 - rr, 0, 1)[..., None] ** 1.5
    bgc = base + (255 - base) * light * 0.22
    f2 = Image.fromarray(bgc.clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")
    warn = []
    has_text = bool((text or "").strip())
    behind = layout == "behind"
    # 1. element cutout (tight)
    el = None
    if element is not None:
        el = element.convert("RGBA")
        bb = el.getchannel("A").getbbox()
        el = el.crop(bb) if bb else el
    else:
        warn.append("no element provided")
    # 2. sticker headline tiles, rendered big and scaled down to fit
    if has_text:
        dark_bg = lum(bg_hex) < 0.35
        if dark_bg:
            fill, s_in, s_out = rgb("#ffffff"), None, tuple(int(v * 0.32) for v in rgb(bg_hex))
        else:
            cand = [colors.get("primary"), colors.get("background"), colors.get("text"), "#3b1670"]
            fc = next((c_ for c_ in cand if c_ and contrast(c_, bg_hex) >= 3 and lum(c_) < 0.3), "#3b1670")
            fill, s_in, s_out = rgb(fc), (255, 255, 255), tuple(int(v * 0.45) for v in rgb(fc))
        # one tile per line count; the circle fit below keeps whichever comes out biggest
        tiles = []
        for n in (1, 2, 3):
            t_ = _sticker_text(text, 0, 0, fill, s_in, s_out, 200, n_lines=n)
            if t_ is not None:
                bb = t_.getchannel("A").getbbox()
                tiles.append(t_.crop(bb) if bb else t_)
        if not tiles:
            warn.append("Menchers text too long for the round logo")
    else:
        tiles = []

    def pick(cand):
        best_ = None
        for c_ in cand:  # cand is in 1, 2, 3 line order
            if best_ is None or c_[0][0] > best_[0][0] * 1.12:
                best_ = c_
        return best_

    def pts_of(img):
        ys, xs = np.where(np.asarray(img.getchannel("A")) > 40)
        st = max(1, int(math.sqrt(len(xs) / 15000)))
        return xs[::st].astype(np.float32) - img.width / 2, ys[::st].astype(np.float32) - img.height / 2

    def biggest(img, lim, y_lo, y_hi, top_max=None, bot_max=None):
        """Largest scale (and centre y in [y_lo, y_hi]) at which img sits inside the circle of radius lim
        centred on (cx, cy); optional limits on its top / bottom edge."""
        xs, ys = pts_of(img)
        best = (0.0, cy)
        for yc in np.arange(y_lo, y_hi + 0.1, 3):
            lo, hi = 0.0, 4 * lim / max(img.width, img.height) * 2
            for _ in range(28):
                m = (lo + hi) / 2
                ok = float(np.sqrt((xs * m) ** 2 + (ys * m + yc - cy) ** 2).max()) <= lim
                if ok and top_max is not None:
                    ok = yc - img.height * m / 2 >= top_max
                if ok:
                    ok = yc + img.height * m / 2 <= min(BOT, bot_max if bot_max is not None else BOT)
                lo, hi = (m, hi) if ok else (lo, m)
            if lo > best[0] * 1.002:
                best = (lo, yc)
        return best

    def put(img, s_, yc):
        w_, h_ = max(1, round(img.width * s_)), max(1, round(img.height * s_))
        im = down(img, (w_, h_))
        x_, y_ = round(cx - w_ / 2), round(yc - h_ / 2)
        return im, x_, y_

    R_EL = R * 1.06  # the element may sit a little closer to the rim than the headline
    placed_text, placed_el = None, None
    if tiles and el is not None and behind:
        # element as big as the circle, headline as big as the circle over its middle (bitcoin / wheel tokens)
        s_e, yc_e = biggest(el, R_EL, cy - 30, cy + 10)
        placed_el = put(el, s_e, yc_e)
        cand = [(biggest(t_, R * 0.95, cy - 30, cy + 10), t_) for t_ in tiles]
        (s_t, yc_t), t_ = pick(cand)
        placed_text = put(t_, s_t, yc_t)
    elif tiles and el is not None:
        # headline across the top of the circle, element under it (gold box / copper coin tokens)
        cand = [(biggest(t_, R, cy - R * 0.6, cy - R * 0.15, bot_max=cy + R * 0.02), t_) for t_ in tiles]
        (s_t, yc_t), t_ = pick(cand)
        placed_text = put(t_, s_t, yc_t)
        tb = placed_text[2] + placed_text[0].height
        s_e, yc_e = biggest(el, R_EL, tb - 10, cy + R_EL, top_max=tb - placed_text[0].height * 0.22)
        placed_el = put(el, s_e, yc_e)
    elif tiles:
        cand = [(biggest(t_, R, cy - 20, cy + 20), t_) for t_ in tiles]
        (s_t, yc_t), t_ = pick(cand)
        placed_text = put(t_, s_t, yc_t)
    elif el is not None:
        s_e, yc_e = biggest(el, R_EL, cy - 20, cy + 20)
        placed_el = put(el, s_e, yc_e)
    if placed_el:
        im, x_, y_ = placed_el
        glow = Image.new("RGBA", (size, size), (255, 255, 255, 0))
        gm = Image.new("L", (size, size), 0)
        ImageDraw.Draw(gm).ellipse((x_ - im.width * 0.05, y_ + im.height * 0.2, x_ + im.width * 1.05, y_ + im.height * 1.05), fill=70)
        glow.putalpha(gm.filter(ImageFilter.GaussianBlur(30)))
        f2.alpha_composite(glow)
        f2.alpha_composite(im, (x_, y_))
    if placed_text:
        im, x_, y_ = placed_text
        f2.alpha_composite(im, (x_, y_))
    return f2, warn


def render_round_logo(logo, bg_hex, size=512, content=None):
    """Menchers round logo, rebuilt from the kit's 'file 1' template: file 2 placed at (0,58), the kit's
    overlay light (overlay blend, 68%) at (24,268), clipped by a 511px circle at (1,99), with the group's
    effects (3 inner shadows + top gradient overlay). Transparent 512x512, cut at the bottom like the kit."""
    if content and content.get("mode") == "element":
        f2, warn = menchers_element_file2(content.get("element"), content.get("text"), bg_hex, content.get("colors", {}), 512, content.get("layout", "stack"))
    else:
        f2, warn = menchers_file2(logo, bg_hex, 512)
    H2 = 99 + 511 + 2
    base = np.zeros((H2, 512, 4), dtype=np.float32)
    base[58:58 + 512] = np.asarray(f2, dtype=np.float32) / 255
    col = base[..., :3]
    ovp = os.path.join(HERE, "assets", "menchers_overlay.png")
    if os.path.exists(ovp):
        o = np.asarray(Image.open(ovp).convert("RGBA"), dtype=np.float32) / 255
        layer = np.zeros((H2, 512, 4), dtype=np.float32)
        hh = min(o.shape[0], H2 - 268)
        layer[268:268 + hh, 24:24 + o.shape[1]] = o[:hh]
        a = layer[..., 3:4] * (173 / 255)
        col = col * (1 - a) + _overlay(col, layer[..., :3]) * a
    # circle mask (anti-aliased)
    yy, xx = np.mgrid[0:H2, 0:512].astype(np.float32)
    cx, cy, r = 1 + 255.5, 99 + 255.5, 255.5
    mask = np.clip(r - np.sqrt((xx + 0.5 - cx) ** 2 + (yy + 0.5 - cy) ** 2) + 0.5, 0, 1)
    # gradient overlay: black, 90deg reversed (opaque at top -> clear at bottom), scale 76%, overlay 24%
    top, bot = 99, 99 + 511
    span = (bot - top) * 0.76
    mid = (top + bot) / 2
    t = np.clip((yy - (mid - span / 2)) / span, 0, 1)[..., None]
    ga = (1 - t) * 0.24
    col = col * (1 - ga) + _overlay(col, 0.0) * ga
    # inner shadows (black): overlay 18% size 62, overlay 100% size 40, normal 26% size 51 choke 8
    for size_, op, mode, choke in ((62, 0.18, "overlay", 0), (40, 1.0, "overlay", 0), (51, 0.26, "normal", 8)):
        amt = (_inner_shadow(mask, size_, choke) * op)[..., None]
        tgt = _overlay(col, 0.0) if mode == "overlay" else np.zeros_like(col)
        col = col * (1 - amt) + tgt * amt
    out = np.dstack([col, mask * base[..., 3]])[:512]
    img = Image.fromarray((np.clip(out, 0, 1) * 255).round().astype(np.uint8), "RGBA")
    return img, warn


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
    # full-resolution colour (4:4:4) keeps coloured text and edges sharp; only step down if over the limit
    for q, sub in ((95, 0), (92, 0), (88, 0), (85, 2), (78, 2), (70, 2), (60, 2), (50, 2), (40, 2)):
        buf = io.BytesIO()
        rgbimg.save(buf, "JPEG", quality=q, optimize=True, progressive=True, subsampling=sub)
        if not max_kb or buf.tell() / 1024 <= max_kb:
            break
    return buf.getvalue(), q


def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "banner").lower()).strip("-")
    return s[:40] or "banner"


# ---------------------------------------------------------------- main
class JobError(Exception):
    pass


def validate(job, rel):
    errs = []
    for f in (FONT_HEAD, FONT_BODY, FONT_CTA):
        if not os.path.exists(f):
            errs.append(f"فونت پیدا نشد: {f}")
    arts = job.get("art") or []
    if not arts:
        errs.append("هیچ تصویری در art نیست")
    for a in arts:
        if not os.path.exists(rel(a)):
            errs.append(f"تصویر پیدا نشد: {a}")
    copy = job.get("copy") or {}
    if not (copy.get("headline") or "").strip():
        errs.append("تیتر (copy.headline) خالی است")
    if not (copy.get("cta") or "").strip():
        errs.append("متن دکمه (copy.cta) خالی است")
    lg = (job.get("brand") or {}).get("logo")
    if lg and not os.path.exists(rel(lg)):
        errs.append(f"لوگو پیدا نشد: {lg}")
    if errs:
        raise JobError(" | ".join(errs))


FA_DIG = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(n):
    return str(n).translate(FA_DIG)


def report_fa(results, zip_name):
    lines = [f"✅ {fa(len(results))} فایل ساخته شد."]
    by = {}
    for r in results:
        by.setdefault(r["placement"], []).append(r)
    for pl, rs in by.items():
        sizes = "، ".join(fa(r["size"].replace("x", "×")) for r in rs)
        lines.append(f"• {pl}: {sizes}")
    img_only = [r for r in results if r["text"] == "image-only"]
    if img_only:
        lines.append("ℹ️ فقط تصویر (طبق قوانین پلتفرم، متن را خود پلتفرم کنار تصویر نشان می‌دهد): " + "، ".join(f"{r['placement']} {fa(r['size'].replace('x', '×'))}" for r in img_only))
    probs = [r for r in results if r["text"] == "missing"]
    if probs:
        lines.append("⚠️ تیتر جا نشد (تیتر کوتاه‌تر بده): " + "، ".join(fa(r["size"].replace("x", "×")) for r in probs))
    drops = [r for r in results if any("subtext dropped" in w for w in r["warnings"])]
    if drops:
        lines.append("ℹ️ زیرتیتر به‌خاطر جای کم حذف شد در: " + "، ".join(fa(r["size"].replace("x", "×")) for r in drops))
    big = [r for r in results if any("over the" in w for w in r["warnings"])]
    if big:
        lines.append("⚠️ بیشتر از سقف حجم: " + "، ".join(fa(r["size"].replace("x", "×")) for r in big))
    if any(r.get("scale", 1) > 1 for r in results):
        lines.append("🔍 رندر کامل: هر بنر با همان چیدمان و نسبت، در ۲ تا ۴ برابر پیکسل ساخته شده (در نام فایل ‎@2x / @3x / @4x‎). برای آپلود، به اندازهٔ اصلی کوچکش کن.")
    lines.append(f"📦 فایل ZIP: {zip_name}")
    return "\n".join(lines)


def run(job):
    base = os.path.dirname(os.path.abspath(job.get("_path", ".")))
    rel = lambda p: p if os.path.isabs(p) else os.path.join(base, p)
    with open(os.path.join(HERE, "placements.json"), encoding="utf-8") as f:
        catalog = json.load(f)["placements"]
    validate(job, rel)
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
    needs = []
    for p in chosen:
        pcolors = dict(colors, **p.get("brand", {}).get("colors", {}))
        plogo = None if p.get("noLogo") else logo
        for s in p["sizes"]:
            W0, H0 = s["width"], s["height"]
            # full render: same layout, drawn at k x the pixels (job "scale": "full" (default) | 1 | 2 | 3 | 4)
            sc = job.get("scale", "full")
            k = max(2 if max(W0, H0) <= 2000 else 1, min(4, 1600 // max(W0, H0))) if sc == "full" else max(1, min(4, int(sc)))
            if s.get("kind") == "round-logo":
                k = 1
            global U
            U = k
            W, H = W0 * k, H0 * k
            fmt = (s.get("formats") or ["png"])[0]
            if s.get("kind") == "round-logo":
                tstate = "logo"
                mc = dict(job.get("menchers") or {})
                if mc.get("mode") == "element":
                    if mc.get("element") and os.path.exists(rel(mc["element"])):
                        e_img = Image.open(rel(mc["element"]))
                        if e_img.mode == "RGBA" and e_img.getchannel("A").getextrema()[0] < 250:
                            mc["element"] = e_img  # already a cut-out
                        else:
                            mc["element"] = key_backdrop(e_img.convert("RGB"))
                    if not isinstance(mc.get("element"), Image.Image):  # fall back to the campaign element cut from the approved picture
                        pr = next((element_parts(a_) for a_ in arts if element_parts(a_) is not None), None)
                        mc["element"] = pr[1] if pr else smart_crop(arts[0], 512, 512).convert("RGBA")
                    mc["colors"] = pcolors
                img, warns = render_round_logo(logo, brand.get("logo_bg") or pcolors.get("primary") or pcolors["background"], W, mc)
                data, q = encode(img, "png")
                fname = f"{p['id']}/{name}_logo_round.png"
            else:
                logo_only = s.get("logoOnly") and plogo is not None
                art_only = (not logo_only) and s.get("artOnly") and not job.get("text_on_image_only_slots")
                lay = compute_layout(W, H, rtl, art_only, s.get("safeZone"))
                lay["style"] = job.get("style", "blend")
                tstate = "image-only" if art_only else ("logo" if logo_only else "ok")
                if logo_only:
                    img = Image.new("RGBA", (W, H), rgb(pcolors["background"]) + (255,))
                    paste_logo(img, plogo, W * 0.15, H * 0.15, W * 0.7, H * 0.7, "center")
                    warns = []
                else:
                    _, _, aw, ah = (round(v) for v in lay["art"])
                    src = pick_art(arts, aw, ah)
                    art = smart_crop(src, aw, ah)
                    if job.get("flip_art"):
                        art = art.transpose(Image.FLIP_LEFT_RIGHT)
                    done = False
                    parts = None
                    if not art_only and job.get("style") != "panel":
                        for cand in [src] + [a_ for a_ in arts if a_ is not src]:
                            parts = element_parts(cand.transpose(Image.FLIP_LEFT_RIGHT) if job.get("flip_art") else cand)
                            if parts is not None:
                                break
                    if parts is not None:
                        field, el = parts
                        l1 = element_layout(W, H, rtl, el, field)
                        img, warns = render_banner(W, H, None, plogo, pcolors, copy, l1)
                        tb = ink_box(l1["_pre_text"], img)
                        if tb is not None and not any("headline too long" in w for w in warns):
                            used = (tb[2] - tb[0]) if (W / H >= 1.0) else (tb[3] - tb[1])
                            l2 = element_layout(W, H, rtl, el, field, used + 4)
                            img2, warns2 = render_banner(W, H, None, plogo, pcolors, copy, l2)
                            if not any("headline too long" in w for w in warns2) and len(warns2) <= len(warns):
                                img, warns = img2, warns2
                        done = not any("headline too long" in w for w in warns)
                        if done and l1.get("_small"):
                            needs.append((W0, H0))
                    if not done:
                        if lay["mode"] == "full" and not art_only:
                            s_ = src.transpose(Image.FLIP_LEFT_RIGHT) if job.get("flip_art") else src
                            best = None
                            sides = [lay["side"]]
                            if lay["side"] == "bottom" and W / H >= 1.0:
                                sides.append("right" if rtl else "left")
                            for sd in sides:
                                cand_l = dict(lay, side=sd)
                                if sd != lay["side"]:
                                    cw_ = round(W * 0.56)
                                    cand_l["content"] = (W - cw_, 0, cw_, H) if sd == "right" else (0, 0, cw_, H)
                                # crops: attention crop, and crops anchored away from the text side / to the top
                                crops = [art, anchor_crop(s_, W, H, sd)]
                                if plain_border(s_, sd):
                                    crops += [pad_fit(s_, W, H, sd, z) for z in (1.0, 0.85)]
                                for cimg in crops:
                                    fl = fit_free(cand_l, cimg)
                                    if fl is not None:
                                        free = fl["content"][2] * fl["content"][3]
                                        if best is None or free > best[0]:
                                            best = (free, fl, cimg)
                                if best:
                                    break
                            if best is None:
                                # no clean space: move the picture aside; the strip/tower step below decides how to fill
                                lay = reflow_layout(lay)
                                art = smart_crop(s_, max(8, round(lay["art"][2])), max(8, round(lay["art"][3])))
                            else:
                                _, lay, art = best
                        if lay["mode"] in ("strip", "tower") and not art_only and lay["style"] == "blend":
                            # seam side of the picture is busy -> fading it out would smear objects: use the clean card
                            m_ = saliency(art)
                            gh_, gw_ = m_.shape
                            if lay["mode"] == "strip":
                                seam = m_[:, : max(1, gw_ // 4)] if lay["art"][0] > 0 else m_[:, -max(1, gw_ // 4):]
                            else:
                                seam = m_[-max(1, gh_ // 4):, :]
                            s_ = src.transpose(Image.FLIP_LEFT_RIGHT) if job.get("flip_art") else src
                            ts = "bottom" if lay["mode"] == "tower" else ("right" if lay["art"][0] == 0 else "left")
                            if seam.mean() > 0.65 and plain_border(s_, ts):
                                # plain backdrop: show the whole picture and continue its backdrop under the copy
                                for z in (1.0, 0.85, 0.7):
                                    cand = pad_fit(s_, W, H, ts, z)
                                    cx_, cy_, cw_, ch_ = (round(v) for v in lay["content"])
                                    mm = saliency(cand.crop((cx_, cy_, cx_ + max(1, cw_), cy_ + max(1, ch_))))
                                    if mm.mean() < 0.02:
                                        lay["card"] = True  # prebuilt full canvas
                                        art = cand
                                        seam = seam * 0
                                        break
                            if seam.mean() > 0.65:
                                lay["card"] = True
                                art = card_canvas(smart_crop(s_, max(8, round(lay["art"][2])), max(8, round(lay["art"][3]))), W, H, lay["art"])
                                needs.append((W0, H0))
                        img, warns = render_banner(W, H, art, plogo, pcolors, {} if art_only else copy, lay)
                        if not art_only and job.get("tighten", True):
                            nl = tighten(W, H, art, plogo, pcolors, copy, lay, img)
                            if nl is not None:
                                img2, warns2 = render_banner(W, H, art, plogo, pcolors, copy, nl)
                                if not any("headline too long" in w for w in warns2):
                                    img, warns = img2, warns2
                    if art_only:
                        warns.append("image only: the platform shows the title/CTA")
                data, q = encode(img, fmt, s.get("maxKB") if k == 1 else None)
                ext = "jpg" if fmt == "jpg" else fmt
                sid = "" if s["id"] == f"{W0}x{H0}" else f"{s['id']}_"
                fname = f"{p['id']}/{name}_{p['id']}_{sid}{W0}x{H0}" + (f"@{k}x" if k > 1 else "") + f".{ext}"
            path = os.path.join(out, fname)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
            kb = round(len(data) / 1024)
            if s.get("maxKB") and kb > s["maxKB"] and k == 1:
                warns.append(f"{kb} KB is over the {s['maxKB']} KB limit")
            if tstate == "ok" and any("headline too long" in w for w in warns):
                tstate = "missing"
            results.append({"text": tstate, "file": fname, "placement": p.get("name_fa") or p["name"], "slot": s.get("label_fa") or s.get("label") or s["id"], "size": f"{W0}x{H0}", "px": f"{W}x{H}", "scale": k, "kb": kb, "warnings": warns})
            previews.append((fname, img))
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    zpath = os.path.join(os.path.dirname(out), f"{name}-banners.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for r in results:
            z.write(os.path.join(out, r["file"]), r["file"])
        z.write(os.path.join(out, "manifest.json"), "manifest.json")
    # contact sheet for showing in chat: every banner with its size caption, nothing else
    cols = 4
    cw, rh, cap = 380, 300, 34
    rows = math.ceil(len(previews) / cols) or 1
    sheet = Image.new("RGB", (cols * cw, rows * rh), (244, 244, 247))
    capf = Text(FONT_BODY, 15)
    dsh = ImageDraw.Draw(sheet)
    for i, ((fname, im), r) in enumerate(zip(previews, results)):
        t = im.copy()
        t.thumbnail((360, rh - cap - 14))
        bgc = Image.new("RGBA", t.size, (210, 210, 215, 255))
        bgc.alpha_composite(t.convert("RGBA"))
        x0, y0 = (i % cols) * cw, (i // cols) * rh
        sheet.paste(bgc.convert("RGB"), (x0 + (cw - t.width) // 2, y0 + 8 + (rh - cap - 14 - t.height) // 2))
        label = f"{r['placement']} · {fa(r['size'].replace('x', '×'))}" + (" · فقط تصویر" if r["text"] == "image-only" else "")
        while capf.width(label) > cw - 16 and len(label) > 8:
            label = label[:-2]
        capf.draw(dsh, (x0 + cw / 2 - capf.width(label) / 2, y0 + rh - cap / 2 - 4), label, (60, 60, 70), anchor="lm")
    sheet.save(os.path.join(out, "preview.png"))
    buckets = {}
    for w_, h_ in needs:
        r_ = w_ / h_
        b = "wide" if r_ >= 2.6 else "landscape" if r_ >= 1.15 else "square" if r_ >= 0.8 else "portrait"
        buckets.setdefault(b, []).append(f"{w_}x{h_}")
    side_fa = "سمت چپ" if rtl else "سمت راست"
    needs_art = [{"shape": b, "sizes": v, "file": f"/mnt/data/fix_{b}.png",
                  "prompt": {"wide": "very wide panorama (about 3:1)", "landscape": "landscape 3:2", "square": "square 1:1", "portrait": "portrait 2:3"}[b]
                  + f": same scene, style, colours and lighting. Main subject compact and complete, fully inside the {'LEFT' if rtl else 'RIGHT'} half"
                  + (" (or the top half for portrait)" if b == "portrait" else "")
                  + f". The other half is a clean, plain backdrop of the scene's main colour (solid or very soft gradient) with nothing in it: no props, no scenery, no light rays, no text."} for b, v in buckets.items()]
    return {"report_fa": report_fa(results, os.path.basename(zpath)), "needs_art": needs_art, "zip": zpath, "preview": os.path.join(out, "preview.png"), "count": len(results), "rtl": rtl, "raqm": RAQM, "unknown_placements": missing, "files": results}


if __name__ == "__main__":
    jp = sys.argv[1] if len(sys.argv) > 1 else "job.json"
    with open(jp, encoding="utf-8") as f:
        job = json.load(f)
    job["_path"] = jp
    try:
        res = run(job)
    except JobError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(2)
    print(json.dumps(res, ensure_ascii=False, indent=2))
