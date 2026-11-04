// Local image helpers (sharp): data URLs, palette extraction, logo crop, fitting, demo art.
import sharp from 'sharp';

export function dataUrlToBuffer(dataUrl) {
  const m = /^data:([^;]+);base64,(.*)$/s.exec(dataUrl || '');
  if (!m) throw Object.assign(new Error('Expected a base64 data URL image'), { status: 400 });
  return Buffer.from(m[2], 'base64');
}

export const bufferToDataUrl = (buf, mime = 'image/png') => `data:${mime};base64,${buf.toString('base64')}`;

export async function imageSize(buf) {
  const { width, height } = await sharp(buf).metadata();
  return { width, height };
}

// Resize art to an exact size without distortion: scale to cover, crop around the most "interesting" region.
export async function fitExact(buf, width, height) {
  return sharp(buf)
    .resize(width, height, { fit: 'cover', position: sharp.strategy.attention })
    .png()
    .toBuffer();
}

const hex = (r, g, b) => '#' + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');

// Dominant colours via k-means on a downscaled copy. Returns [{hex, share}] sorted by share.
export async function extractPalette(buf, k = 6) {
  const { data, info } = await sharp(buf).flatten({ background: '#ffffff' }).resize(80, 80, { fit: 'inside' }).raw().toBuffer({ resolveWithObject: true });
  const px = [];
  for (let i = 0; i < data.length; i += info.channels) px.push([data[i], data[i + 1], data[i + 2]]);
  let centers = Array.from({ length: k }, (_, i) => px[Math.floor((i + 0.5) * px.length / k)].slice());
  let assign = new Array(px.length).fill(0);
  for (let iter = 0; iter < 12; iter++) {
    for (let p = 0; p < px.length; p++) {
      let best = 0, bd = Infinity;
      for (let c = 0; c < k; c++) {
        const d = (px[p][0] - centers[c][0]) ** 2 + (px[p][1] - centers[c][1]) ** 2 + (px[p][2] - centers[c][2]) ** 2;
        if (d < bd) { bd = d; best = c; }
      }
      assign[p] = best;
    }
    const sums = centers.map(() => [0, 0, 0, 0]);
    px.forEach((p, i) => { const s = sums[assign[i]]; s[0] += p[0]; s[1] += p[1]; s[2] += p[2]; s[3]++; });
    centers = sums.map((s, i) => (s[3] ? [s[0] / s[3], s[1] / s[3], s[2] / s[3]] : centers[i]));
  }
  const counts = centers.map(() => 0);
  assign.forEach((a) => counts[a]++);
  return centers
    .map((c, i) => ({ hex: hex(...c), share: counts[i] / px.length }))
    .filter((c) => c.share > 0.01)
    .sort((a, b) => b.share - a.share);
}

// Crop a normalised box out of an image; if the crop's corners share one flat colour, key it out to transparency.
export async function cropLogo(buf, box) {
  const { width, height } = await imageSize(buf);
  const pad = 0.01;
  const left = Math.max(0, Math.floor((box.x - pad) * width));
  const top = Math.max(0, Math.floor((box.y - pad) * height));
  const w = Math.min(width - left, Math.ceil((box.w + pad * 2) * width));
  const h = Math.min(height - top, Math.ceil((box.h + pad * 2) * height));
  if (w < 8 || h < 8) return null;
  const { data, info } = await sharp(buf).extract({ left, top, width: w, height: h }).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const at = (x, y) => (y * info.width + x) * 4;
  const corners = [at(0, 0), at(info.width - 1, 0), at(0, info.height - 1), at(info.width - 1, info.height - 1)].map((i) => [data[i], data[i + 1], data[i + 2]]);
  const avg = corners.reduce((a, c) => a.map((v, j) => v + c[j] / 4), [0, 0, 0]);
  const flat = corners.every((c) => Math.hypot(c[0] - avg[0], c[1] - avg[1], c[2] - avg[2]) < 24);
  if (flat) {
    for (let i = 0; i < data.length; i += 4) {
      const d = Math.hypot(data[i] - avg[0], data[i + 1] - avg[1], data[i + 2] - avg[2]);
      if (d < 28) data[i + 3] = 0;
      else if (d < 60) data[i + 3] = Math.round(data[i + 3] * ((d - 28) / 32));
    }
  }
  const out = await sharp(data, { raw: info }).trim({ threshold: 1 }).png().toBuffer().catch(() => sharp(data, { raw: info }).png().toBuffer());
  return { png: out, backgroundRemoved: flat };
}

// ---------- Demo-mode artwork (used when no OpenAI key is configured) ----------
function rng(seedStr) {
  let h = 2166136261;
  for (const ch of seedStr) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return () => ((h = Math.imul(h ^ (h >>> 15), 2246822507) ^ Math.imul(h ^ (h >>> 13), 3266489909)) >>> 0) / 4294967296;
}

const PALETTES = [
  ['#1b1446', '#6a2c91', '#f15bb5', '#fee440'],
  ['#03045e', '#0077b6', '#00b4d8', '#ffd166'],
  ['#2b2d42', '#ef233c', '#edf2f4', '#ffb703'],
  ['#073b3a', '#0b6e4f', '#08a045', '#f4d35e'],
  ['#3d0c02', '#c1440e', '#f6aa1c', '#fff1d0'],
];

// side = where text should go ("left" | "bottom" | "none"); subject is placed opposite.
export async function demoArt({ seed, width, height, side = 'none', hueShift = 0 }) {
  const r = rng(seed);
  const pal = PALETTES[Math.floor(r() * PALETTES.length)];
  const min = Math.min(width, height);
  let cx = width / 2, cy = height / 2;
  if (side === 'left') cx = width * 0.7;
  if (side === 'bottom') cy = height * 0.38;
  const blobs = Array.from({ length: 7 }, () => `<circle cx="${r() * width}" cy="${r() * height}" r="${min * (0.15 + r() * 0.35)}" fill="${pal[1 + Math.floor(r() * 3)]}" opacity="${0.25 + r() * 0.3}"/>`).join('');
  const s = min * 0.32;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${pal[0]}"/><stop offset="1" stop-color="${pal[1]}"/></linearGradient>
    <radialGradient id="hero" cx="0.35" cy="0.3" r="0.8"><stop offset="0" stop-color="${pal[3]}"/><stop offset="1" stop-color="${pal[2]}"/></radialGradient>
    <filter id="b"><feGaussianBlur stdDeviation="${min * 0.06}"/></filter>
  </defs>
  <rect width="100%" height="100%" fill="url(#g)"/>
  <g filter="url(#b)">${blobs}</g>
  <ellipse cx="${cx}" cy="${cy + s * 1.05}" rx="${s * 0.9}" ry="${s * 0.12}" fill="#000" opacity="0.25" filter="url(#b)"/>
  <circle cx="${cx}" cy="${cy}" r="${s}" fill="url(#hero)"/>
  <rect x="${cx - s * 0.35}" y="${cy - s * 0.35}" width="${s * 0.7}" height="${s * 0.7}" rx="${s * 0.12}" fill="${pal[0]}" opacity="0.85" transform="rotate(${Math.floor(r() * 40) - 20} ${cx} ${cy})"/>
</svg>`;
  return sharp(Buffer.from(svg)).modulate({ hue: hueShift }).png().toBuffer();
}

export async function demoEdit(buf) {
  return sharp(buf).modulate({ hue: 35, saturation: 1.15 }).png().toBuffer();
}

// Heuristic colour roles from a measured palette: largest area = background, most saturated distinct colour = accent.
export function pickRoles(hexes) {
  const toRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const sat = (h) => { const c = toRgb(h); const mx = Math.max(...c), mn = Math.min(...c); return mx ? (mx - mn) / mx : 0; };
  const light = (h) => { const [r, g, b] = toRgb(h); return (0.299 * r + 0.587 * g + 0.114 * b) / 255; };
  const dist = (a, b) => { const x = toRgb(a), y = toRgb(b); return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]); };
  const background = hexes[0] || '#101828';
  const others = hexes.slice(1).filter((h) => dist(h, background) > 60);
  const accent = [...others].sort((a, b) => sat(b) - sat(a))[0] || '#ff5a1f';
  const primary = others.find((h) => h !== accent) || accent;
  const text = light(background) > 0.55 ? '#111111' : '#ffffff';
  const ctaText = light(accent) > 0.6 ? '#111111' : '#ffffff';
  return { background, primary, accent, text, ctaText };
}

// Re-encode a PNG: stamp DPI and, if needed, step down to palette PNG until it fits maxKB.
export async function finalizePng(buf, { maxKB, dpi } = {}) {
  const base = () => (dpi ? sharp(buf).withMetadata({ density: dpi }) : sharp(buf));
  let out = await base().png({ compressionLevel: 9 }).toBuffer();
  if (!maxKB || out.length / 1024 <= maxKB) return out;
  for (const colours of [256, 128, 64, 32]) {
    out = await base().png({ palette: true, colours, quality: 90, effort: 10, dither: 1 }).toBuffer();
    if (out.length / 1024 <= maxKB) break;
  }
  return out;
}
