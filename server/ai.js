// All OpenAI calls live here. Without OPENAI_API_KEY the app runs in demo mode with local placeholders.
import OpenAI, { toFile } from 'openai';
import { pickRoles, bufferToDataUrl, cropLogo, dataUrlToBuffer, demoArt, demoEdit, extractPalette, fitExact, imageSize } from './imaging.js';

const KEY = process.env.OPENAI_API_KEY;
export const DEMO = !KEY;
const client = KEY ? new OpenAI({ apiKey: KEY, organization: process.env.OPENAI_ORG_ID || undefined, project: process.env.OPENAI_PROJECT_ID || undefined }) : null;
const TEXT_MODEL = process.env.OPENAI_TEXT_MODEL || 'gpt-5.5';
const IMAGE_MODEL = process.env.OPENAI_IMAGE_MODEL || 'gpt-image-2';
const IMAGE_QUALITY = process.env.OPENAI_IMAGE_QUALITY || 'high';
// gpt-image-2+ accepts any WxH (multiples of 16, ratio 1:3..3:1); older models only the three standard sizes.
const FREE_SIZES = /^gpt-image-(2|[3-9])/.test(IMAGE_MODEL);

export const config = { demo: DEMO, textModel: TEXT_MODEL, imageModel: IMAGE_MODEL };

const NO_TEXT = 'ABSOLUTE RULE: the image must contain no text of any kind: no letters, words, numbers, logos, brand marks, signage, watermarks, buttons, badges, price tags or call-to-action shapes. Edge-to-edge artwork, no borders, frames or device mockups.';

const textSide = (w, h, rtl) => (w / h >= 1.4 ? (rtl ? 'right' : 'left') : 'bottom');
const isRtl = (b) => /[\u0590-\u08FF]/.test(`${b.business} ${b.promotion} ${b.message}`);
const spaceInstruction = (side) =>
  side === 'none'
    ? 'Fill the whole frame with the hero subject, centred, with comfortable breathing room around it.'
    : side === 'left' || side === 'right'
      ? `Place the hero subject in the ${side === 'left' ? 'right' : 'left'} half. Keep the ${side} ~45% calm and uncluttered (soft background only) so a headline and button can be added there later.`
      : 'Place the hero subject in the upper-middle area. Keep the bottom ~40% calm and uncluttered (soft background only) so a headline and button can be added there later.';

function briefText(b) {
  return `Business: ${b.business}\nPromotion / offer: ${b.promotion}\nAd message / copy: ${b.message}${b.audience ? `\nAudience: ${b.audience}` : ''}`;
}

// Pick a generation size with the target's aspect ratio (or the nearest the model supports).
function genSize(w, h) {
  if (!FREE_SIZES) {
    const r = w / h;
    return r > 1.2 ? '1536x1024' : r < 0.83 ? '1024x1536' : '1024x1024';
  }
  const r = Math.min(3, Math.max(1 / 3, w / h));
  const area = 1536 * 1024;
  let gw = Math.sqrt(area * r), gh = gw / r;
  const s16 = (v) => Math.max(256, Math.round(v / 16) * 16);
  return `${s16(gw)}x${s16(gh)}`;
}

async function json(system, user, schema, name) {
  const res = await client.chat.completions.create({
    model: TEXT_MODEL,
    messages: [{ role: 'system', content: system }, { role: 'user', content: user }],
    response_format: { type: 'json_schema', json_schema: { name, strict: true, schema } },
  });
  return JSON.parse(res.choices[0].message.content);
}

const b64 = (res) => Buffer.from(res.data[0].b64_json, 'base64');

async function editImage(buf, prompt, size) {
  const res = await client.images.edit({
    model: IMAGE_MODEL,
    image: await toFile(buf, 'source.png', { type: 'image/png' }),
    prompt,
    size,
    quality: IMAGE_QUALITY,
    ...(IMAGE_MODEL.startsWith('gpt-image-1') ? { input_fidelity: 'high' } : {}),
  });
  return b64(res);
}

// ---------------- Step 2: five ideas ----------------
const ideaSchema = {
  type: 'object', additionalProperties: false, required: ['ideas'],
  properties: {
    ideas: {
      type: 'array', minItems: 5, maxItems: 5,
      items: {
        type: 'object', additionalProperties: false,
        required: ['title', 'hook', 'visual', 'mood', 'palette'],
        properties: {
          title: { type: 'string', description: 'Short punchy name for the idea' },
          hook: { type: 'string', description: 'One sentence: why it stops the scroll and fits the message' },
          visual: { type: 'string', description: 'Concrete description of the key visual (subject, setting, composition, lighting). No text in the image.' },
          mood: { type: 'string' },
          palette: { type: 'string', description: 'Colour direction' },
        },
      },
    },
  },
};

export async function ideas(brief) {
  if (DEMO) {
    const base = [
      ['Hero in the Spotlight', 'A single hero product lit like a stage star', 'cinematic, premium'],
      ['Everyday Magic', 'The product transforming an ordinary moment into something joyful', 'warm, playful'],
      ['Bold Geometry', 'Graphic, colour-blocked shapes framing the offer', 'modern, confident'],
      ['Before / After Split', 'A visual split showing life before and after the offer', 'clear, persuasive'],
      ['Miniature World', 'A tiny diorama world built around the product', 'whimsical, crafted'],
    ];
    return base.map(([title, visual, mood]) => ({
      title, mood, palette: 'brand-led with one vivid accent',
      hook: `Makes "${brief.promotion}" for ${brief.business} instantly memorable.`,
      visual: `${visual} for ${brief.business}.`,
    }));
  }
  const out = await json(
    'You are an award-winning creative director at a digital advertising agency. You invent banner ad concepts that are genuinely surprising yet instantly readable at small sizes. Each idea must be visually distinct from the others (different metaphor, setting and composition). The visual must work WITHOUT any text in the image, since copy is added separately.',
    `${briefText(brief)}\n\nPropose exactly 5 very creative banner concepts.`,
    ideaSchema, 'banner_ideas');
  return out.ideas;
}

// ---------------- Step 3: text-free concept + edits ----------------
const MASTER = { landscape: [1536, 1024], square: [1024, 1024], portrait: [1024, 1536] };

function conceptPrompt(brief, idea, side, brand) {
  return [
    'Create a premium advertising key visual to be used as a banner background.',
    briefText(brief),
    `Creative idea: "${idea.title}". ${idea.visual} Mood: ${idea.mood}. Colour direction: ${idea.palette}.`,
    brand?.colors ? `Use this brand palette: ${Object.values(brand.colors).join(', ')}.` : '',
    `Composition: ${spaceInstruction(side)}`,
    'Clean, high-contrast and readable at very small sizes; strong single focal point.',
    NO_TEXT,
  ].filter(Boolean).join('\n');
}

export async function concept({ brief, idea, orientation = 'landscape', brand }) {
  const [w, h] = MASTER[orientation] || MASTER.landscape;
  const side = textSide(w, h, isRtl(brief));
  if (DEMO) return demoArt({ seed: idea.title + brief.business, width: w, height: h, side });
  const res = await client.images.generate({ model: IMAGE_MODEL, prompt: conceptPrompt(brief, idea, side, brand), size: `${w}x${h}`, quality: IMAGE_QUALITY });
  return b64(res);
}

export async function edit({ image, instruction }) {
  const buf = dataUrlToBuffer(image);
  if (DEMO) return demoEdit(buf);
  const { width, height } = await imageSize(buf);
  const prompt = `Edit this advertising visual: ${instruction}\nKeep everything not mentioned identical (composition, subject, style, lighting, palette).\n${NO_TEXT}`;
  const out = await editImage(buf, prompt, FREE_SIZES ? `${width}x${height}` : genSize(width, height));
  return fitExact(out, width, height);
}

export async function harmonize({ image, colors }) {
  return edit({ image, instruction: `Re-grade the colours so the artwork harmonises with this brand palette: ${colors.join(', ')}. Keep subject and composition the same.` });
}

// ---------------- Step 6: recompose for a placement ----------------
// side: where text will sit inside this art region ("left" | "bottom" | "none").
export async function adapt({ image, width, height, side, seed }) {
  const buf = dataUrlToBuffer(image);
  const src = await imageSize(buf);
  const srcR = src.width / src.height, dstR = width / height;
  // Same shape (within 12%) → a high-quality resize is enough; no need to spend a generation.
  if (Math.abs(Math.log(dstR / srcR)) < 0.12) return { png: await fitExact(buf, width, height), method: 'resized' };
  // Without a key we can't redraw: smart-crop around the most important region instead.
  if (DEMO) return { png: await fitExact(buf, width, height), method: 'smart-cropped (no API key)' };
  const prompt = [
    `Recompose this exact advertising visual for a ${width}x${height} px ad placement (aspect ratio ${dstR.toFixed(2)}:1).`,
    'It must look like the same campaign: same hero subject, style, lighting, palette and mood.',
    'Re-arrange the scene for the new frame: extend the background naturally and reposition or rescale the subject so nothing important is cut off. Do not stretch, squash, letterbox, add padding or simply crop.',
    spaceInstruction(side),
    NO_TEXT,
  ].join('\n');
  const out = await editImage(buf, prompt, genSize(width, height));
  return { png: await fitExact(out, width, height), method: 'recomposed' };
}

// ---------------- Step 4: brand extraction ----------------
const brandSchema = {
  type: 'object', additionalProperties: false,
  required: ['headlineFont', 'bodyFont', 'colors', 'logo', 'notes'],
  properties: {
    headlineFont: { $ref: '#/$defs/font' },
    bodyFont: { $ref: '#/$defs/font' },
    colors: {
      type: 'object', additionalProperties: false,
      required: ['background', 'primary', 'accent', 'text', 'ctaText'],
      properties: {
        background: { type: 'string', description: 'hex' }, primary: { type: 'string', description: 'hex' },
        accent: { type: 'string', description: 'hex, used for the CTA button' }, text: { type: 'string', description: 'hex' },
        ctaText: { type: 'string', description: 'hex, readable on accent' },
      },
    },
    logo: {
      type: 'object', additionalProperties: false, required: ['present', 'x', 'y', 'w', 'h'],
      properties: { present: { type: 'boolean' }, x: { type: 'number' }, y: { type: 'number' }, w: { type: 'number' }, h: { type: 'number' } },
      description: 'Tight bounding box of the logo, normalised 0-1 relative to image width/height',
    },
    notes: { type: 'string', description: 'One sentence on the visual style' },
  },
  $defs: {
    font: {
      type: 'object', additionalProperties: false, required: ['family', 'weight', 'uppercase'],
      properties: {
        family: { type: 'string', description: 'Closest matching Google Fonts family name' },
        weight: { type: 'integer', description: '100-900' },
        uppercase: { type: 'boolean' },
      },
    },
  },
};

export async function brand({ image }) {
  const buf = dataUrlToBuffer(image);
  const palette = await extractPalette(buf);
  if (DEMO) {
    const p = palette.map((c) => c.hex);
    const roles = pickRoles(p);
    return {
      demo: true, palette: p,
      colors: roles,
      headlineFont: { family: 'Montserrat', weight: 800, uppercase: false },
      bodyFont: { family: 'Inter', weight: 400, uppercase: false },
      logo: null, notes: 'Demo mode: colours were measured from your image; font and logo detection need an OpenAI key.',
    };
  }
  const res = await client.chat.completions.create({
    model: TEXT_MODEL,
    response_format: { type: 'json_schema', json_schema: { name: 'brand_kit', strict: true, schema: brandSchema } },
    messages: [
      { role: 'system', content: 'You are a brand designer. From an existing ad or brand image, identify the typography (closest Google Fonts families), the brand colour roles, and the logo location. Measured dominant colours are provided; prefer them for hex values.' },
      { role: 'user', content: [
        { type: 'text', text: `Measured dominant colours (by area): ${palette.map((c) => `${c.hex} ${(c.share * 100).toFixed(0)}%`).join(', ')}. Return the brand kit.` },
        { type: 'image_url', image_url: { url: image, detail: 'high' } },
      ] },
    ],
  });
  const kit = JSON.parse(res.choices[0].message.content);
  let logo = null;
  if (kit.logo.present && kit.logo.w > 0.01 && kit.logo.h > 0.01) {
    const cropped = await cropLogo(buf, kit.logo).catch(() => null);
    if (cropped) logo = { dataUrl: bufferToDataUrl(cropped.png), backgroundRemoved: cropped.backgroundRemoved };
  }
  return { ...kit, palette: palette.map((c) => c.hex), logo };
}
