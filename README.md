# Banner Studio

Internal tool: brief → 5 AI ideas → text-free concept → edits → brand kit (optional) → headline/sub/CTA → placements → ZIP of exact-size banners.

## Two ways to use it
- **No API key (ChatGPT Team):** make ideas and text-free art with the *Banner Concept Studio* Custom GPT (setup in `custom-gpt/`), then in the app choose **Start from my own artwork** and upload the landscape/square/portrait/wide images. Each placement starts from the closest shape and is smart-cropped; brand kit colours, copy, exact sizes and the ZIP all work without a key.
- **With an OpenAI API key:** the whole flow runs inside the app, including ideas, edits, font/logo detection and true per-ratio recomposition.

## Run locally
```bash
npm install
cp .env.example .env        # add OPENAI_API_KEY (leave empty for demo mode)
npm run build               # builds the web UI
npm start                   # http://localhost:8787
```
Dev mode with hot reload: `npm --prefix client install && npm run dev` (UI on :5173).

Docker: `docker build -t banner-studio . && docker run -p 8787:8787 --env-file .env banner-studio`

## How it works
| Step | What happens | Where |
|---|---|---|
| Ideas | Text model returns exactly 5 distinct concepts (JSON schema) | `server/ai.js` `ideas()` |
| Concept | Image model renders the chosen idea with **no text/CTA**, reserving negative space for copy | `concept()` |
| Edits | Natural-language edits on the current version, with version history | `edit()` |
| Brand kit | Colours measured locally (k-means), fonts + colour roles + logo box from a vision call; logo is cropped and flat backgrounds keyed out | `brand()`, `server/imaging.js` |
| Copy | Headline / subtext / CTA drawn as real type on canvas (exact spelling, brand fonts via Google Fonts) | `client/src/lib/render.js` |
| Placements | Each size gets a layout (full-bleed, side-by-side strip, or stacked tower). If the art region's shape differs from the master, the image model **recomposes** the scene for that ratio (not crop/pad); otherwise it's a smart resize | `computeLayout()`, `adapt()` |
| Export | PNG/JPG/WebP at exact pixels; JPG/WebP quality auto-steps down to meet each placement's KB limit; ZIP + manifest.json | `client/src/lib/export.js` |

## Placements
`server/placements.json` holds the Yektanet placements from the *Ad Specifications Guide* (Sep 2026). Picking a placement exports **all** its sizes.
- Placement: `id, name, group, notes?, brand? {colors}` (forced colours, e.g. Vinzy #141032), `noLogo?`, `sizes[]`
- Size: `id, width, height, formats[]` (first = default), `maxKB?`, `dpi?`, `label?`, `artOnly?` (platform shows its own title/CTA, so the image is exported without copy), `logoOnly?` (icons), `safeZone?`
- JPG/WebP quality steps down to meet `maxKB`; PNGs over the limit are re-encoded server-side with a reduced palette; `dpi` is stamped into PNGs.
- Persian/RTL copy is detected automatically: text is right-aligned, layouts mirror, and Vazirmatn is used as the Persian fallback font.
Not covered: video, interactive/playable ads, GIF animation. Cafe Bazaar is intentionally left out.

## Notes
- A ChatGPT Team/Business workspace can't be called by apps; this needs an OpenAI **API** key (platform.openai.com). The key stays on the server.
- `gpt-image-2` accepts any size, so recomposition targets the exact ratio (clamped to 1:3–3:1, then fitted). With `gpt-image-1` the nearest of 3 standard sizes is used.
