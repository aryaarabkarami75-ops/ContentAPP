import 'dotenv/config';
import express from 'express';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as ai from './ai.js';
import { bufferToDataUrl, dataUrlToBuffer, finalizePng } from './imaging.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const app = express();
app.use(express.json({ limit: '40mb' }));

// Optional shared password (HTTP Basic auth): set APP_PASSWORD to enable.
if (process.env.APP_PASSWORD) {
  app.use((req, res, next) => {
    const [, encoded = ''] = (req.headers.authorization || '').split(' ');
    const pass = Buffer.from(encoded, 'base64').toString().split(':').slice(1).join(':');
    if (pass === process.env.APP_PASSWORD) return next();
    res.set('WWW-Authenticate', 'Basic realm="Banner Studio"').status(401).send('Password required');
  });
}

const placementsFile = process.env.PLACEMENTS_FILE || path.join(here, 'placements.json');
const route = (fn) => async (req, res) => {
  try { res.json(await fn(req.body || {})); }
  catch (err) {
    console.error(err);
    res.status(err.status || 500).json({ error: err.error?.message || err.message || 'Something went wrong' });
  }
};
const need = (body, ...keys) => {
  for (const k of keys) if (!body[k]) throw Object.assign(new Error(`Missing "${k}"`), { status: 400 });
};

app.get('/api/config', (_req, res) => {
  const { placements } = JSON.parse(fs.readFileSync(placementsFile, 'utf8'));
  res.json({ ...ai.config, placements });
});

app.post('/api/ideas', route(async (b) => { need(b, 'brief'); return { ideas: await ai.ideas(b.brief) }; }));
app.post('/api/concept', route(async (b) => { need(b, 'brief', 'idea'); return { image: bufferToDataUrl(await ai.concept(b)) }; }));
app.post('/api/edit', route(async (b) => { need(b, 'image', 'instruction'); return { image: bufferToDataUrl(await ai.edit(b)) }; }));
app.post('/api/harmonize', route(async (b) => { need(b, 'image', 'colors'); return { image: bufferToDataUrl(await ai.harmonize(b)) }; }));
app.post('/api/brand', route(async (b) => { need(b, 'image'); return ai.brand(b); }));
app.post('/api/adapt', route(async (b) => {
  need(b, 'image', 'width', 'height');
  const { png, method } = await ai.adapt({ ...b, width: Math.round(b.width), height: Math.round(b.height), side: b.side || 'none', seed: b.seed || 'x' });
  return { image: bufferToDataUrl(png), method };
}));

app.post('/api/finalize-png', route(async (b) => {
  need(b, 'image');
  return { image: bufferToDataUrl(await finalizePng(dataUrlToBuffer(b.image), { maxKB: b.maxKB, dpi: b.dpi })) };
}));

const dist = path.join(here, '..', 'client', 'dist');
if (fs.existsSync(dist)) {
  app.use(express.static(dist));
  app.get('*', (_req, res) => res.sendFile(path.join(dist, 'index.html')));
}

const port = process.env.PORT || 8787;
app.listen(port, () => console.log(`Banner Studio API on :${port} (${ai.config.demo ? 'DEMO mode, no OpenAI key' : `text=${ai.config.textModel} image=${ai.config.imageModel}`})`));
