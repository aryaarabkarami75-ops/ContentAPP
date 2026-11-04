import JSZip from 'jszip';

const MIME = { png: 'image/png', jpg: 'image/jpeg', webp: 'image/webp' };
const toBlob = (canvas, type, q) => new Promise((r) => canvas.toBlob(r, type, q));

// Encode a canvas, stepping quality down (JPG/WebP) until it fits the placement's file-size limit.
export async function encode(canvas, format, maxKB, dpi) {
  const type = MIME[format];
  if (format === 'png') {
    let blob = await toBlob(canvas, type);
    if ((maxKB && blob.size / 1024 > maxKB) || dpi) {
      // Browsers can't compress PNG or set its DPI; the server re-encodes it (reduced palette if needed) and stamps the DPI.
      const res = import.meta.env.VITE_LOCAL === '1' ? { ok: false } : await fetch('/api/finalize-png', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image: canvas.toDataURL('image/png'), maxKB, dpi }) });
      if (res.ok) { const { image } = await res.json(); blob = await (await fetch(image)).blob(); }
    }
    return { blob, quality: null, overLimit: maxKB ? blob.size / 1024 > maxKB : false };
  }
  let q = 0.92, blob;
  for (;;) {
    blob = await toBlob(canvas, type, q);
    if (!maxKB || blob.size / 1024 <= maxKB || q <= 0.4) break;
    q = Math.round((q - 0.07) * 100) / 100;
  }
  return { blob, quality: q, overLimit: maxKB ? blob.size / 1024 > maxKB : false };
}

export async function downloadZip(items, name) {
  const zip = new JSZip();
  items.forEach((it) => zip.file(it.filename, it.blob));
  zip.file('manifest.json', JSON.stringify(items.map(({ filename, placement, size, sizeKB, format }) => ({ filename, placement: placement.name, slot: size.label || size.id, width: size.width, height: size.height, format, sizeKB })), null, 2));
  const blob = await zip.generateAsync({ type: 'blob' });
  // Inside a claude.ai page, downloads go through the viewer's save prompt.
  const downloads = window.claude?.use ? await window.claude.use('downloads').catch(() => null) : null;
  if (downloads) { await downloads.save({ filename: `${name}.zip`, data: blob }); return; }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${name}.zip`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

export const slug = (s) => (s || 'banner').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'banner';
