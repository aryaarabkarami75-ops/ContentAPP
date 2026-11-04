// Responsive banner layout + canvas renderer. The same code draws previews and final exports.

// Decide how a placement of size W×H is structured.
//  full  – art fills the canvas, copy sits in the art's reserved negative space (start side or bottom)
//  strip – very wide (leaderboards, mobile banners): copy panel + art panel side by side
//  tower – very tall (skyscrapers, half page): art on top, copy panel below
//  art   – image only (the platform shows its own title/CTA next to it)
// rtl mirrors everything horizontally so Persian/Arabic copy reads from the right.
export function computeLayout(W, H, { safeZone, rtl = false, artOnly = false } = {}) {
  const r = W / H;
  let mode, art, content, side;
  if (artOnly) {
    return { mode: 'art', side: 'none', art: { x: 0, y: 0, w: W, h: H }, content: { x: 0, y: 0, w: 0, h: 0 }, W, H, rtl, insets: { top: 0, left: 0, right: 0 } };
  }
  if (r >= 2.6) {
    mode = 'strip';
    // Ultra-wide but tall enough (e.g. 3408×504, 1081×144): give the art a wider 3:1 panel so the banner doesn't look empty.
    const wide = r > 5 && H >= 120;
    const artW = Math.round(Math.min(W * (wide ? 0.5 : 0.38), H * (wide ? 3 : 1.7)));
    art = { x: rtl ? 0 : W - artW, y: 0, w: artW, h: H };
    content = { x: rtl ? artW : 0, y: 0, w: W - artW, h: H };
    side = 'none';
  } else if (r <= 0.5) {
    mode = 'tower';
    const artH = Math.round(H * 0.46);
    art = { x: 0, y: 0, w: W, h: artH };
    content = { x: 0, y: artH, w: W, h: H - artH };
    side = 'none';
  } else {
    mode = 'full';
    art = { x: 0, y: 0, w: W, h: H };
    side = r >= 1.4 ? (rtl ? 'right' : 'left') : 'bottom';
    const cw = Math.round(W * 0.56);
    content = side === 'left' ? { x: 0, y: 0, w: cw, h: H } : side === 'right' ? { x: W - cw, y: 0, w: cw, h: H } : { x: 0, y: Math.round(H * 0.55), w: W, h: Math.round(H * 0.45) };
  }
  // Keep copy out of the platform's unsafe zones.
  if (safeZone) {
    const t = (safeZone.top || 0) * H, b = H - (safeZone.bottom || 0) * H, l = (safeZone.left || 0) * W, rt = W - (safeZone.right || 0) * W;
    const x1 = Math.max(content.x, l), y1 = Math.max(content.y, t), x2 = Math.min(content.x + content.w, rt), y2 = Math.min(content.y + content.h, b);
    content = { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
  }
  const insets = { top: (safeZone?.top || 0) * H, left: (safeZone?.left || 0) * W, right: (safeZone?.right || 0) * W };
  return { mode, side, art, content, W, H, insets, rtl };
}

export const isRtl = (s) => /[\u0590-\u08FF]/.test(s || '');

// ---------- colour helpers ----------
const rgb = (hex) => { const h = hex.replace('#', ''); const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
const lum = (hex) => { const [r, g, b] = rgb(hex).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
export const contrast = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
const readable = (preferred, bg) => (preferred && contrast(preferred, bg) >= 4.5 ? preferred : contrast('#ffffff', bg) >= contrast('#111111', bg) ? '#ffffff' : '#111111');
const rgba = (hex, a) => `rgba(${rgb(hex).join(',')},${a})`;

// ---------- text fitting ----------
function wrap(ctx, text, maxW) {
  const words = text.split(/\s+/).filter(Boolean);
  const lines = [];
  let cur = '';
  for (const w of words) {
    const t = cur ? cur + ' ' + w : w;
    if (ctx.measureText(t).width <= maxW || !cur) cur = t; else { lines.push(cur); cur = w; }
  }
  if (cur) lines.push(cur);
  return lines;
}

function fit(ctx, text, font, maxW, maxH, maxSize, minSize, maxLines, lh = 1.12) {
  if (!text) return { size: 0, lines: [], height: 0 };
  for (let size = Math.floor(maxSize); size >= minSize; size -= Math.max(1, Math.round(size * 0.04))) {
    ctx.font = `${font.weight} ${size}px ${stack(font.family)}`;
    const lines = wrap(ctx, text, maxW);
    const widest = Math.max(...lines.map((l) => ctx.measureText(l).width));
    const height = lines.length * size * lh;
    if (lines.length <= maxLines && widest <= maxW && height <= maxH) return { size, lines, height, lh };
  }
  return null;
}

const stack = (family) => `"${family}", "Vazirmatn", system-ui, sans-serif`;
const caps = (s, font) => (font.uppercase ? (s || '').toUpperCase() : s || '');

function drawLines(ctx, block, font, x, y, align, color) {
  ctx.font = `${font.weight} ${block.size}px ${stack(font.family)}`;
  ctx.fillStyle = color;
  ctx.textAlign = align;
  ctx.textBaseline = 'top';
  block.lines.forEach((l, i) => ctx.fillText(l, x, y + i * block.size * block.lh));
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

function measureCta(ctx, label, font, h, maxW = Infinity) {
  let size = Math.round(h * 0.42), tw;
  for (;;) {
    ctx.font = `700 ${size}px ${stack(font.family)}`;
    tw = ctx.measureText(label).width;
    if (tw + size * 1.6 <= maxW || size <= 8) break;
    size -= 1;
  }
  return { size, w: Math.ceil(Math.min(maxW, tw + Math.max(h * 1.1, size * 1.6))) };
}

function drawCta(ctx, label, font, x, y, h, w, size, colors) {
  ctx.save();
  ctx.shadowColor = 'rgba(0,0,0,0.25)'; ctx.shadowBlur = h * 0.25; ctx.shadowOffsetY = h * 0.06;
  roundRect(ctx, x, y, w, h, h * 0.28);
  ctx.fillStyle = colors.accent; ctx.fill();
  ctx.restore();
  ctx.font = `700 ${size}px ${stack(font.family)}`;
  ctx.fillStyle = readable(colors.ctaText, colors.accent);
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(label, x + w / 2, y + h / 2 + size * 0.04);
}

function drawLogo(ctx, logo, x, y, maxW, maxH, align = 'left') {
  if (!logo) return 0;
  const s = Math.min(maxW / logo.width, maxH / logo.height);
  const w = logo.width * s, h = logo.height * s;
  const dx = align === 'center' ? x + (maxW - w) / 2 : align === 'right' ? x + maxW - w : x;
  ctx.drawImage(logo, dx, y, w, h);
  return h;
}

// ---------- main renderer ----------
// art: image sized exactly to layout.art; logo: optional image; brand: {colors, headlineFont, bodyFont}; copy: {headline, sub, cta}
// opts: flipArt (mirror the artwork), logoOnly (icon: logo on brand colour)
export function renderBanner(canvas, { layout, art, logo, brand, copy, flipArt = false, logoOnly = false }) {
  const { W, H, mode, side, content, rtl } = layout;
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d');
  ctx.direction = rtl ? 'rtl' : 'ltr';
  const c = { ...brand.colors };
  // A CTA that blends into the panel is invisible: fall back to primary, then to a high-contrast colour.
  if (contrast(c.accent, c.background) < 1.8) c.accent = contrast(c.primary, c.background) >= 1.8 ? c.primary : readable(null, c.background);
  const hf = brand.headlineFont, bf = brand.bodyFont;
  const minDim = Math.min(W, H);
  const warnings = [];

  ctx.fillStyle = c.background;
  ctx.fillRect(0, 0, W, H);
  if (logoOnly && logo) {
    drawLogo(ctx, logo, W * 0.15, H * 0.15 + (H * 0.7 - Math.min(H * 0.7, (W * 0.7) * logo.height / logo.width)) / 2, W * 0.7, H * 0.7, 'center');
    return { warnings };
  }
  if (art) {
    const a = layout.art;
    ctx.save();
    if (flipArt) { ctx.translate(a.x + a.w, a.y); ctx.scale(-1, 1); ctx.drawImage(art, 0, 0, a.w, a.h); }
    else ctx.drawImage(art, a.x, a.y, a.w, a.h);
    ctx.restore();
  }
  if (mode === 'art') return { warnings };

  // Scrims / blends so copy stays legible and panels merge with the art.
  let g;
  if (mode === 'full' && (side === 'left' || side === 'right')) {
    g = side === 'left' ? ctx.createLinearGradient(0, 0, W * 0.7, 0) : ctx.createLinearGradient(W, 0, W * 0.3, 0);
    g.addColorStop(0, rgba(c.background, 0.88)); g.addColorStop(0.55, rgba(c.background, 0.55)); g.addColorStop(1, rgba(c.background, 0));
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  } else if (mode === 'full') {
    g = ctx.createLinearGradient(0, H, 0, H * 0.4);
    g.addColorStop(0, rgba(c.background, 0.92)); g.addColorStop(0.5, rgba(c.background, 0.6)); g.addColorStop(1, rgba(c.background, 0));
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  } else if (mode === 'strip') {
    const a = layout.art, bw = a.w * 0.45;
    const x0 = rtl ? a.x + a.w : a.x;
    g = ctx.createLinearGradient(x0, 0, rtl ? x0 - bw : x0 + bw, 0);
    g.addColorStop(0, rgba(c.background, 1)); g.addColorStop(1, rgba(c.background, 0));
    ctx.fillStyle = g; ctx.fillRect(rtl ? x0 - bw : x0, 0, bw, H);
  } else if (mode === 'tower') {
    const a = layout.art;
    g = ctx.createLinearGradient(0, a.h, 0, a.h * 0.7);
    g.addColorStop(0, rgba(c.background, 1)); g.addColorStop(1, rgba(c.background, 0));
    ctx.fillStyle = g; ctx.fillRect(0, a.h * 0.7, W, a.h * 0.3 + 1);
  }

  const textColor = readable(c.text, c.background);
  const headline = caps(copy.headline, hf), sub = caps(copy.sub, bf), cta = copy.cta || '';
  const pad = Math.max(6, Math.round(minDim * 0.07));
  const box = { x: content.x + pad, y: content.y + pad, w: content.w - pad * 2, h: content.h - pad * 2 };
  const startAlign = rtl ? 'right' : 'left';

  // ----- inline row (short strips like 728×90, 468×60) -----
  if (mode === 'strip' && H < 130) {
    // Work in "distance from the start edge" and mirror for RTL.
    const X = (d, w = 0) => (rtl ? box.x + box.w - d - w : box.x + d);
    let d = 0;
    if (logo) { const lh = H * 0.42; const lw = Math.min(box.w * 0.18, (logo.width / logo.height) * lh); drawLogo(ctx, logo, X(d, lw), (H - lh) / 2, lw, lh, startAlign); d += lw + pad; }
    let ctaW = 0;
    if (cta) {
      const ch = Math.round(Math.max(18, H * 0.46));
      const m = measureCta(ctx, cta, bf, ch, box.w * 0.34);
      ctaW = m.w;
      drawCta(ctx, cta, bf, X(box.w - ctaW, ctaW), (H - ch) / 2, ch, ctaW, m.size, c);
    }
    const tw = box.w - ctaW - pad - d;
    const twoRows = H >= 70 && sub;
    const head = fit(ctx, headline, hf, tw, (twoRows ? 0.6 : 1) * box.h, box.h * (twoRows ? 0.5 : 0.62), 9, 2);
    const subB = twoRows && head ? fit(ctx, sub, bf, tw, box.h - head.height - 2, head.size * 0.6, 9, 1) : null;
    if (!head) warnings.push('Headline is too long for this size');
    else {
      const total = head.height + (subB ? subB.height + 2 : 0);
      const y = (H - total) / 2;
      const tx = rtl ? box.x + box.w - d : box.x + d;
      drawLines(ctx, head, hf, tx, y, startAlign, textColor);
      if (subB) drawLines(ctx, subB, bf, tx, y + head.height + 2, startAlign, textColor);
      else if (sub) warnings.push('Subtext dropped (no room)');
    }
    return { warnings };
  }

  // ----- stacked copy (everything else) -----
  const align = mode === 'strip' || side === 'left' || side === 'right' ? startAlign : 'center';
  const ax = align === 'left' ? box.x : align === 'right' ? box.x + box.w : box.x + box.w / 2;
  let top = box.y, avail = box.h;

  if (logo) {
    const lh = Math.round(Math.min(Math.max(minDim * 0.09, 14), minDim * 0.14));
    if (mode === 'full') {
      // Logo sits in the top corner (start side) of the whole canvas, or centred above bottom copy.
      const ins = layout.insets, lw = minDim * 0.4;
      const lx = align === 'left' ? ins.left + pad : align === 'right' ? W - ins.right - pad - lw : (W - lw) / 2;
      drawLogo(ctx, logo, lx, ins.top + pad, lw, lh, align);
      // Side layouts: keep the copy block below the logo.
      if (side !== 'bottom') { const used = ins.top + pad + lh + pad * 0.6 - top; if (used > 0) { top += used; avail -= used; } }
    } else {
      drawLogo(ctx, logo, box.x, top, box.w, lh, align);
      top += lh + pad * 0.7; avail -= lh + pad * 0.7;
    }
  }

  const ch = cta ? Math.round(Math.min(Math.max(minDim * (mode === 'strip' ? 0.2 : 0.11), 22), avail * 0.22)) : 0;
  const gap = Math.round(Math.max(4, avail * 0.04));
  const textH = avail - (cta ? ch + gap * 1.6 : 0);
  const headMax = mode === 'strip' ? Math.min(box.w * 0.12, textH * 0.42) : Math.min(minDim * 0.15, textH * 0.5);
  let head, subB = null;
  // Shrink the headline step by step to make room for the subtext before giving up on it.
  for (let share = sub ? 0.62 : 1, tries = 0; tries < 4; share -= 0.08, tries++) {
    head = fit(ctx, headline, hf, box.w, textH * share, headMax * (1 - tries * 0.12), 10, 3, rtl ? 1.3 : 1.08);
    if (!head || !sub) break;
    subB = fit(ctx, sub, bf, box.w, textH - head.height - gap, Math.max(10, head.size * 0.46), Math.max(9, Math.round(minDim * 0.03)), 3, rtl ? 1.45 : 1.25);
    if (subB) break;
  }
  if (head && sub && !subB) warnings.push('Subtext dropped (no room)');
  if (!head) warnings.push('Headline is too long for this size');
  const blockH = (head?.height || 0) + (subB ? gap + subB.height : 0) + (cta ? gap * 1.6 + ch : 0);
  // start-side/strip/tower: vertically centred in the copy box; bottom: anchored to the bottom.
  let y = mode === 'full' && side === 'bottom' ? top + avail - blockH : top + (avail - blockH) / 2;
  if (head) { drawLines(ctx, head, hf, ax, y, align, textColor); y += head.height; }
  if (subB) { y += gap; drawLines(ctx, subB, bf, ax, y, align, textColor); y += subB.height; }
  if (cta) {
    y += gap * 1.6;
    const m = measureCta(ctx, cta, bf, ch, box.w);
    const w = m.w;
    const cx = align === 'left' ? box.x : align === 'right' ? box.x + box.w - w : box.x + (box.w - w) / 2;
    drawCta(ctx, cta, bf, cx, y, ch, w, m.size, c);
  }
  return { warnings };
}

export function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Could not load image'));
    img.src = src;
  });
}
