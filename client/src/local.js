// Browser-only implementations of the server routes used in no-key mode, so the app can run as a static page.
import placementsFile from '../../server/placements.json';
import { loadImage } from './lib/render.js';

const canvasOf = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };

// Crop-to-fill around the most "interesting" region (edges + saturation), like sharp's attention strategy.
async function smartCrop(src, W, H) {
  const img = await loadImage(src);
  const iw = img.width, ih = img.height;
  const scale = Math.max(W / iw, H / ih);
  const cw = W / scale, ch = H / scale; // crop window in source pixels
  const gs = 96 / Math.max(iw, ih), gw = Math.max(8, Math.round(iw * gs)), gh = Math.max(8, Math.round(ih * gs));
  const g = canvasOf(gw, gh).getContext('2d', { willReadFrequently: true });
  g.drawImage(img, 0, 0, gw, gh);
  const px = g.getImageData(0, 0, gw, gh).data;
  const lum = new Float32Array(gw * gh), energy = new Float32Array(gw * gh);
  for (let i = 0; i < gw * gh; i++) { const r = px[i * 4], gr = px[i * 4 + 1], b = px[i * 4 + 2]; lum[i] = 0.299 * r + 0.587 * gr + 0.114 * b; const mx = Math.max(r, gr, b), mn = Math.min(r, gr, b); energy[i] = mx ? ((mx - mn) / mx) * 40 : 0; }
  for (let y = 0; y < gh - 1; y++) for (let x = 0; x < gw - 1; x++) { const i = y * gw + x; energy[i] += Math.abs(lum[i] - lum[i + 1]) + Math.abs(lum[i] - lum[i + gw]); }
  const wx = Math.round(cw * gs), wy = Math.round(ch * gs);
  let best = -1, bx = 0, by = 0;
  for (let y0 = 0; y0 <= gh - wy; y0++) for (let x0 = 0; x0 <= gw - wx; x0++) {
    if ((gw - wx) > 0 && (gh - wy) > 0) { /* both axes free only when rounding; fine */ }
    let s = 0;
    for (let y = y0; y < y0 + wy; y++) for (let x = x0; x < x0 + wx; x++) s += energy[y * gw + x];
    if (s > best) { best = s; bx = x0; by = y0; }
  }
  const sx = Math.min(iw - cw, Math.max(0, bx / gs)), sy = Math.min(ih - ch, Math.max(0, by / gs));
  const out = canvasOf(W, H);
  const ctx = out.getContext('2d'); ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(img, sx, sy, cw, ch, 0, 0, W, H);
  return out.toDataURL('image/png');
}

async function palette(src, k = 6) {
  const img = await loadImage(src);
  const s = 80 / Math.max(img.width, img.height);
  const w = Math.max(1, Math.round(img.width * s)), h = Math.max(1, Math.round(img.height * s));
  const c = canvasOf(w, h).getContext('2d', { willReadFrequently: true });
  c.fillStyle = '#fff'; c.fillRect(0, 0, w, h); c.drawImage(img, 0, 0, w, h);
  const d = c.getImageData(0, 0, w, h).data, pts = [];
  for (let i = 0; i < d.length; i += 4) pts.push([d[i], d[i + 1], d[i + 2]]);
  let cen = Array.from({ length: k }, (_, i) => pts[Math.floor((i + 0.5) * pts.length / k)].slice());
  const as = new Array(pts.length).fill(0);
  for (let it = 0; it < 12; it++) {
    pts.forEach((p, i) => { let bd = Infinity; cen.forEach((q, j) => { const dd = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2; if (dd < bd) { bd = dd; as[i] = j; } }); });
    const sums = cen.map(() => [0, 0, 0, 0]);
    pts.forEach((p, i) => { const t = sums[as[i]]; t[0] += p[0]; t[1] += p[1]; t[2] += p[2]; t[3]++; });
    cen = sums.map((t, j) => (t[3] ? [t[0] / t[3], t[1] / t[3], t[2] / t[3]] : cen[j]));
  }
  const counts = cen.map(() => 0); as.forEach((a) => counts[a]++);
  const hex = (v) => '#' + v.map((x) => Math.round(x).toString(16).padStart(2, '0')).join('');
  return cen.map((v, j) => ({ hex: hex(v), share: counts[j] / pts.length })).filter((x) => x.share > 0.01).sort((a, b) => b.share - a.share).map((x) => x.hex);
}

function pickRoles(hexes) {
  const toRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const sat = (h) => { const c = toRgb(h); const mx = Math.max(...c), mn = Math.min(...c); return mx ? (mx - mn) / mx : 0; };
  const light = (h) => { const [r, g, b] = toRgb(h); return (0.299 * r + 0.587 * g + 0.114 * b) / 255; };
  const dist = (a, b) => { const x = toRgb(a), y = toRgb(b); return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]); };
  const background = hexes[0] || '#101828';
  const others = hexes.slice(1).filter((h) => dist(h, background) > 60);
  const accent = [...others].sort((a, b) => sat(b) - sat(a))[0] || '#ff5a1f';
  const primary = others.find((h) => h !== accent) || accent;
  return { background, primary, accent, text: light(background) > 0.55 ? '#111111' : '#ffffff', ctaText: light(accent) > 0.6 ? '#111111' : '#ffffff' };
}

export async function localApi(path, body) {
  switch (path) {
    case 'config': return { demo: true, local: true, textModel: '', imageModel: '', placements: placementsFile.placements };
    case 'adapt': return { image: await smartCrop(body.image, Math.round(body.width), Math.round(body.height)), method: 'smart-cropped' };
    case 'brand': {
      const p = await palette(body.image);
      return { palette: p, colors: pickRoles(p), headlineFont: { family: 'Vazirmatn', weight: 800, uppercase: false }, bodyFont: { family: 'Vazirmatn', weight: 500, uppercase: false }, logo: null, notes: 'Colours were measured from your image. Pick fonts and upload the logo below.' };
    }
    case 'finalize-png': return { image: body.image };
    default: throw new Error('This step needs the AI server. Use the Banner Concept Studio plugin in ChatGPT for ideas and artwork.');
  }
}
