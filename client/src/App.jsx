import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api, fileToDataUrl } from './api.js';
import { computeLayout, isRtl, loadImage, renderBanner } from './lib/render.js';
import { FONT_CHOICES, loadFont } from './lib/fonts.js';
import { downloadZip, encode, slug } from './lib/export.js';
import JSZip from 'jszip';

// Accept images and/or the plugin's ZIP; landscape (or the first image) becomes the master.
async function artFromFiles(files) {
  const out = [];
  for (const f of files) {
    if (/\.zip$/i.test(f.name) || f.type.includes('zip')) {
      const zip = await JSZip.loadAsync(f);
      for (const e of Object.values(zip.files)) {
        const ext = (e.name.match(/\.(png|jpe?g|webp)$/i) || [])[1];
        if (e.dir || !ext || e.name.includes('__MACOSX')) continue;
        const b64 = await e.async('base64');
        out.push({ name: e.name.split('/').pop(), url: `data:image/${ext.toLowerCase() === 'jpg' ? 'jpeg' : ext.toLowerCase()};base64,${b64}` });
      }
    } else if (f.type.startsWith('image/')) out.push({ name: f.name, url: await fileToDataUrl(f) });
  }
  out.sort((a, b) => (/landscape/i.test(b.name) ? 1 : 0) - (/landscape/i.test(a.name) ? 1 : 0));
  return out.map((x) => x.url);
}

const flipSide = (s) => (s === 'left' ? 'right' : s === 'right' ? 'left' : s);

const STEPS = ['Brief', 'Ideas', 'Concept', 'Brand', 'Copy', 'Placements', 'Export'];
const DEFAULT_BRAND = {
  colors: { background: '#101828', primary: '#1d4ed8', accent: '#ff5a1f', text: '#ffffff', ctaText: '#ffffff' },
  headlineFont: { family: 'Montserrat', weight: 800, uppercase: false },
  bodyFont: { family: 'Inter', weight: 500, uppercase: false },
  logo: null,
};
const QUICK_EDITS = ['Warmer, more inviting colours', 'More empty space for the headline', 'Simplify the background', 'More premium and cinematic', 'Brighter and more energetic'];

export default function App() {
  const [cfg, setCfg] = useState(null);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [brief, setBrief] = useState({ business: '', promotion: '', message: '', audience: '' });
  const [ideas, setIdeas] = useState([]);
  const [idea, setIdea] = useState(null);
  const [orientation, setOrientation] = useState('landscape');
  const [history, setHistory] = useState([]); // concept versions (data URLs)
  const [variants, setVariants] = useState([]); // extra shapes of the approved art (e.g. square / portrait from ChatGPT)
  const [version, setVersion] = useState(0);
  const [brand, setBrand] = useState(DEFAULT_BRAND);
  const [copy, setCopy] = useState({ headline: '', sub: '', cta: '' });
  const [selected, setSelected] = useState([]);
  const [custom, setCustom] = useState([]);
  const [opts, setOpts] = useState({ format: 'auto', textEverywhere: false, flipArt: false });
  const [results, setResults] = useState([]);

  useEffect(() => { api('config').then(setCfg).catch((e) => setError(e.message)); }, []);
  useEffect(() => { loadFont('Vazirmatn', 700); loadFont(brand.headlineFont.family, brand.headlineFont.weight); loadFont(brand.bodyFont.family, brand.bodyFont.weight); }, [brand.headlineFont, brand.bodyFont]);

  const master = history[version];
  const run = async (label, fn) => {
    setBusy(label); setError('');
    try { await fn(); } catch (e) { setError(e.message); } finally { setBusy(''); }
  };

  const getIdeas = () => run('Brainstorming 5 ideas…', async () => {
    const { ideas } = await api('ideas', { brief });
    setIdeas(ideas); setIdea(null); setStep(1);
  });
  const makeConcept = (chosen = idea) => run('Generating the concept visual…', async () => {
    const { image } = await api('concept', { brief, idea: chosen, orientation });
    setHistory([image]); setVersion(0); setStep(2);
  });
  const applyEdit = (instruction) => run('Applying your edit…', async () => {
    const { image } = await api('edit', { image: master, instruction });
    const next = [...history.slice(0, version + 1), image];
    setHistory(next); setVersion(next.length - 1);
  });

  return (
    <div className="app">
      <header>
        <div className="brand-mark">Banner Studio</div>
        {cfg && <span className={`mode ${cfg.demo ? 'demo' : ''}`}>{cfg.local ? 'Artwork comes from the Banner Concept Studio plugin in ChatGPT' : cfg.demo ? 'No API key: AI steps are placeholders. Start from your own artwork' : `Connected · ${cfg.textModel} · ${cfg.imageModel}`}</span>}
      </header>
      <nav className="steps">
        {STEPS.map((s, i) => (
          <button key={s} className={i === step ? 'active' : i < step ? 'done' : ''} disabled={i > step} onClick={() => setStep(i)}>
            <span>{i + 1}</span>{s}
          </button>
        ))}
      </nav>
      {error && <div className="error" onClick={() => setError('')}>{error}</div>}
      {busy && <div className="busy"><div className="spinner" />{busy}</div>}

      <main className={busy ? 'dim' : ''}>
        {step === 0 && <Brief brief={brief} setBrief={setBrief} onNext={getIdeas} demo={cfg?.demo} local={cfg?.local}
          onOwnArt={async (files) => {
            const urls = await artFromFiles(files);
            if (!urls.length) { setError('No images found. Upload PNG/JPG files or the ZIP from the ChatGPT plugin.'); return; }
            setHistory([urls[0]]); setVersion(0); setVariants(urls.slice(1)); setStep(2);
          }} />}
        {step === 1 && (
          <Ideas ideas={ideas} idea={idea} setIdea={setIdea} orientation={orientation} setOrientation={setOrientation}
            onMore={getIdeas} onNext={() => makeConcept()} />
        )}
        {step === 2 && master && (
          <Concept history={history} version={version} setVersion={setVersion} onEdit={applyEdit}
            onRegenerate={() => makeConcept()} onAccept={() => setStep(3)} canEdit={!cfg?.demo} hasIdea={!!idea}
            variants={variants} setVariants={setVariants} />
        )}
        {step === 3 && <Brand demo={cfg?.demo} brand={brand} setBrand={setBrand} run={run} master={master}
          onHarmonize={(colors) => run('Harmonising artwork with brand colours…', async () => {
            const { image } = await api('harmonize', { image: master, colors });
            const next = [...history.slice(0, version + 1), image]; setHistory(next); setVersion(next.length - 1);
          })}
          onNext={() => setStep(4)} />}
        {step === 4 && <Copy copy={copy} setCopy={setCopy} master={master} brand={brand} opts={opts} setOpts={setOpts} onNext={() => setStep(5)} />}
        {step === 5 && cfg && (
          <Placements placements={[...cfg.placements, ...custom]} selected={selected} setSelected={setSelected}
            addCustom={(p) => { setCustom([...custom, p]); setSelected([...selected, p.id]); }}
            opts={opts} setOpts={setOpts}
            onNext={() => run('Building banners…', async () => {
              const list = [...cfg.placements, ...custom].filter((p) => selected.includes(p.id)).flatMap((placement) => placement.sizes.map((size) => ({ placement, size })));
              setResults(await buildAll({ list, master, variants, brand, copy, opts, seed: idea?.title || 'x', setBusy }));
              setStep(6);
            })} />
        )}
        {step === 6 && (
          <Results results={results} brief={brief} canRecompose={!cfg?.demo}
            onRebuild={(r) => run(`Recomposing ${r.placement.name}…`, async () => {
              const [fresh] = await buildAll({ list: [{ placement: r.placement, size: r.size }], master, variants, brand, copy, opts, seed: (idea?.title || 'x') + Date.now(), setBusy, force: true });
              setResults(results.map((x) => (x.key === r.key ? fresh : x)));
            })} />
        )}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------- building
const artCache = new Map();
async function buildOne({ placement, size, master, variants = [], brand: baseBrand, copy, opts, seed, force }) {
  const W = size.width, H = size.height;
  const rtl = isRtl(copy.headline + copy.sub + copy.cta);
  // Platform rules: per-placement colour overrides (e.g. Vinzy) and no-logo placements (e.g. Cafe Bazaar).
  const brand = { ...baseBrand, colors: { ...baseBrand.colors, ...(placement.brand?.colors || {}) }, logo: placement.noLogo ? null : baseBrand.logo };
  const logoOnly = size.logoOnly && !!brand.logo;
  const artOnly = !logoOnly && size.artOnly && !opts.textEverywhere;
  const layout = computeLayout(W, H, { safeZone: size.safeZone, rtl, artOnly });
  const warnings = [];
  let adapted = { method: 'logo on brand colour' }, art = null;
  if (!logoOnly) {
    // Start from whichever art shape (master or uploaded variant) is closest to this placement's art area.
    const target = Math.log(layout.art.w / layout.art.h);
    const sized = await Promise.all([master, ...variants].map(async (src) => { const i = await loadImage(src); return { src, d: Math.abs(Math.log(i.width / i.height) - target) }; }));
    const source = sized.sort((a, b) => a.d - b.d)[0].src;
    // If the art will be mirrored, ask for negative space on the mirrored side.
    const side = opts.flipArt ? flipSide(layout.side) : layout.side;
    const key = `${source.length}:${source.slice(-64)}:${layout.art.w}x${layout.art.h}:${side}`;
    if (force || !artCache.has(key)) artCache.set(key, api('adapt', { image: source, width: layout.art.w, height: layout.art.h, side, seed }));
    try { adapted = await artCache.get(key); } catch (e) { artCache.delete(key); throw e; }
    art = await loadImage(adapted.image);
  }
  const logo = brand.logo ? await loadImage(brand.logo) : null;
  await Promise.all([loadFont('Vazirmatn', 700), loadFont(brand.headlineFont.family, brand.headlineFont.weight), loadFont(brand.bodyFont.family, brand.bodyFont.weight)]);
  const canvas = document.createElement('canvas');
  warnings.push(...renderBanner(canvas, { layout, art, logo, brand, copy: artOnly ? {} : copy, flipArt: opts.flipArt, logoOnly }).warnings);
  if (artOnly) warnings.push('Image only: the platform adds the title/CTA');
  const allowed = size.formats || ['png', 'jpg', 'webp'];
  let fmt = opts.format === 'auto' ? allowed[0] : opts.format;
  if (!allowed.includes(fmt)) { warnings.push(`${fmt.toUpperCase()} not allowed here, used ${allowed[0].toUpperCase()}`); fmt = allowed[0]; }
  const { blob, quality, overLimit } = await encode(canvas, fmt, size.maxKB, fmt === 'png' ? size.dpi : undefined);
  if (overLimit) warnings.push(`File is ${Math.round(blob.size / 1024)} KB, over the ${size.maxKB} KB limit`);
  return { key: `${placement.id}/${size.id}`, placement, size, blob, url: URL.createObjectURL(blob), sizeKB: Math.round(blob.size / 1024), quality, format: fmt, method: adapted.method, mode: layout.mode, warnings };
}

async function buildAll({ list, setBusy, ...rest }) {
  const out = new Array(list.length);
  let done = 0, i = 0;
  const worker = async () => {
    while (i < list.length) {
      const idx = i++;
      out[idx] = await buildOne({ ...list[idx], ...rest });
      setBusy(`Building banners… ${++done}/${list.length}`);
    }
  };
  await Promise.all(Array.from({ length: Math.min(3, list.length) }, worker));
  return out;
}

// ---------------------------------------------------------------- steps
function Field({ label, hint, children }) {
  return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}

function Brief({ brief, setBrief, onNext, onOwnArt, demo, local }) {
  const set = (k) => (e) => setBrief({ ...brief, [k]: e.target.value });
  const ok = brief.business && brief.promotion && brief.message;
  const upload = (
    <label className={`button ${local ? 'primary-solid' : demo ? 'primary-ish' : ''}`}>{local ? 'Upload the artwork' : 'Start from my own artwork'}
      <input id="art-upload" type="file" accept="image/*,.zip,application/zip" multiple hidden onChange={(e) => e.target.files?.length && onOwnArt(e.target.files)} />
    </label>
  );
  if (local) {
    return (
      <section className="card narrow">
        <h2>Start a campaign</h2>
        <ol className="how">
          <li>In ChatGPT, run <b>@Banner Concept Studio</b> with your brief, pick an idea and approve it.</li>
          <li>Upload its ZIP here as it is (or the images inside it).</li>
          <li>Add the brand kit and copy, pick placements, and download every size as one ZIP.</li>
        </ol>
        <Field label="Campaign or business name" hint="Used to name the exported files."><input id="biz" value={brief.business} onChange={set('business')} placeholder="e.g. Wallgold" /></Field>
        <div className="actions">{upload}</div>
      </section>
    );
  }
  return (
    <section className="card narrow">
      <h2>Tell us about the campaign</h2>
      <Field label="Business" hint="What they do, who they serve, tone of the brand."><textarea rows={3} value={brief.business} onChange={set('business')} placeholder="e.g. Nava Coffee, a specialty coffee chain in Tehran with a young, design-loving crowd" /></Field>
      <Field label="Promotion"><textarea rows={2} value={brief.promotion} onChange={set('promotion')} placeholder="e.g. 30% off all cold brews this week" /></Field>
      <Field label="Ad message / copywrite"><textarea rows={2} value={brief.message} onChange={set('message')} placeholder="e.g. Beat the heat with the smoothest cold brew in town" /></Field>
      <Field label="Audience (optional)"><input value={brief.audience} onChange={set('audience')} placeholder="e.g. students and young professionals" /></Field>
      <div className="actions">
        <button className="primary" disabled={!ok} onClick={onNext}>Suggest 5 ideas</button>
        {upload}
      </div>
      <p className="muted small">Made the visuals in ChatGPT? Upload them here (landscape, square and portrait if you have them) and skip straight to brand, copy and sizes.</p>
    </section>
  );
}

function Ideas({ ideas, idea, setIdea, orientation, setOrientation, onMore, onNext }) {
  return (
    <section>
      <h2>Pick the idea you like most</h2>
      <div className="ideas">
        {ideas.map((it, i) => (
          <button key={i} className={`idea ${idea === it ? 'picked' : ''}`} onClick={() => setIdea(it)}>
            <b>{it.title}</b><p>{it.hook}</p><p className="muted">{it.visual}</p>
            <div className="tags"><span>{it.mood}</span><span>{it.palette}</span></div>
          </button>
        ))}
      </div>
      <div className="actions">
        <button onClick={onMore}>Give me 5 different ideas</button>
        <label className="inline">Master shape
          <select value={orientation} onChange={(e) => setOrientation(e.target.value)}>
            <option value="landscape">Landscape 3:2</option><option value="square">Square 1:1</option><option value="portrait">Portrait 2:3</option>
          </select>
        </label>
        <button className="primary" disabled={!idea} onClick={onNext}>Generate concept</button>
      </div>
    </section>
  );
}

function Concept({ history, version, setVersion, onEdit, onRegenerate, onAccept, canEdit, hasIdea, variants, setVariants }) {
  const [text, setText] = useState('');
  return (
    <section className="split">
      <div className="stage"><img src={history[version]} alt="Concept" /></div>
      <div className="card side">
        <h3>Text-free concept</h3>
        {canEdit ? (<>
          <p className="muted">Describe any change. The visual stays free of text; copy is added later.</p>
          <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. make the cup bigger and add ice cubes" />
          <div className="chips">{QUICK_EDITS.map((q) => <button key={q} onClick={() => onEdit(q)}>{q}</button>)}</div>
          <div className="actions"><button disabled={!text} onClick={() => { onEdit(text); setText(''); }}>Apply edit</button>{hasIdea && <button onClick={onRegenerate}>Start over</button>}</div>
        </>) : <p className="muted">AI edits need an API key. Make changes in ChatGPT and upload the new version.</p>}
        <h4>Other shapes of this art <span className="muted">(optional)</span></h4>
        <p className="muted small">Each banner size starts from the closest shape, so adding square and portrait versions keeps tall and square banners looking right.</p>
        <div className="thumbs">
          {variants.map((v, i) => <img key={i} src={v} title="Click to remove" onClick={() => setVariants(variants.filter((_, j) => j !== i))} alt={`shape ${i + 1}`} />)}
          <label className="button add">+ Add<input type="file" accept="image/*" multiple hidden onChange={async (e) => { const f = [...(e.target.files || [])]; setVariants([...variants, ...(await Promise.all(f.map(fileToDataUrl)))]); }} /></label>
        </div>
        {history.length > 1 && (<>
          <h4>Versions</h4>
          <div className="thumbs">{history.map((h, i) => <img key={i} src={h} className={i === version ? 'on' : ''} onClick={() => setVersion(i)} alt={`v${i + 1}`} />)}</div>
        </>)}
        <div className="actions"><button className="primary" onClick={onAccept}>Accept this version</button></div>
      </div>
    </section>
  );
}

function Brand({ brand, setBrand, run, onHarmonize, onNext, demo }) {
  const [source, setSource] = useState(null);
  const [notes, setNotes] = useState('');
  const [palette, setPalette] = useState([]);
  const upload = async (e) => {
    const f = e.target.files?.[0]; if (!f) return;
    const url = await fileToDataUrl(f); setSource(url);
    run('Reading fonts, colours and logo…', async () => {
      const kit = await api('brand', { image: url });
      setBrand({ colors: kit.colors, headlineFont: kit.headlineFont, bodyFont: kit.bodyFont, logo: kit.logo?.dataUrl || brand.logo });
      setPalette(kit.palette || []); setNotes(kit.notes || '');
    });
  };
  const uploadLogo = async (e) => { const f = e.target.files?.[0]; if (f) setBrand({ ...brand, logo: await fileToDataUrl(f) }); };
  const setColor = (k) => (e) => setBrand({ ...brand, colors: { ...brand.colors, [k]: e.target.value } });
  const setFont = (k, prop) => (e) => setBrand({ ...brand, [k]: { ...brand[k], [prop]: prop === 'uppercase' ? e.target.checked : prop === 'weight' ? +e.target.value : e.target.value } });
  return (
    <section className="split">
      <div className="card side wide">
        <h3>Brand kit <span className="muted">(optional)</span></h3>
        <p className="muted">Upload a past banner or brand image. We'll pull the fonts, colours and logo from it. You can fine-tune everything below or skip this step.</p>
        <input type="file" accept="image/*" onChange={upload} />
        {source && <img className="source" src={source} alt="Uploaded reference" />}
        {notes && <p className="note">{notes}</p>}
        {palette.length > 0 && <div className="palette">{palette.map((p) => <span key={p} style={{ background: p }} title={p} />)}</div>}
        <div className="actions"><button onClick={onNext}>Skip</button><button className="primary" onClick={onNext}>Use this brand kit</button></div>
      </div>
      <div className="card side">
        <h4>Colours</h4>
        <div className="colors">
          {Object.entries({ background: 'Panel / scrim', text: 'Text', accent: 'CTA button', ctaText: 'CTA text', primary: 'Primary' }).map(([k, l]) => (
            <label key={k}><input type="color" value={brand.colors[k]} onChange={setColor(k)} />{l}</label>
          ))}
        </div>
        {!demo && <button onClick={() => onHarmonize(Object.values(brand.colors))}>Re-tint artwork to these colours</button>}
        {['headlineFont', 'bodyFont'].map((k) => (
          <div key={k}>
            <h4>{k === 'headlineFont' ? 'Headline font' : 'Body & CTA font'}</h4>
            <div className="row">
              <input list="fonts" value={brand[k].family} onChange={setFont(k, 'family')} />
              <select value={brand[k].weight} onChange={setFont(k, 'weight')}>{[300, 400, 500, 600, 700, 800, 900].map((w) => <option key={w}>{w}</option>)}</select>
              <label className="inline"><input type="checkbox" checked={brand[k].uppercase} onChange={setFont(k, 'uppercase')} />CAPS</label>
            </div>
          </div>
        ))}
        <datalist id="fonts">{FONT_CHOICES.map((f) => <option key={f} value={f} />)}</datalist>
        <h4>Logo</h4>
        <div className="row">
          {brand.logo ? <img className="logo" src={brand.logo} alt="Logo" /> : <span className="muted">No logo</span>}
          <input type="file" accept="image/*" onChange={uploadLogo} />
          {brand.logo && <button onClick={() => setBrand({ ...brand, logo: null })}>Remove</button>}
        </div>
      </div>
    </section>
  );
}

function BannerPreview({ width, height, master, brand, copy, flipArt }) {
  const ref = useRef();
  const [warn, setWarn] = useState([]);
  useEffect(() => {
    let live = true;
    (async () => {
      const layout = computeLayout(width, height, { rtl: isRtl(copy.headline + copy.sub + copy.cta) });
      const [art, logo] = await Promise.all([loadImage(master), brand.logo ? loadImage(brand.logo) : null]);
      await Promise.all([loadFont('Vazirmatn', 700), loadFont(brand.headlineFont.family, brand.headlineFont.weight), loadFont(brand.bodyFont.family, brand.bodyFont.weight)]);
      if (live && ref.current) setWarn(renderBanner(ref.current, { layout, art, logo, brand, copy, flipArt }).warnings);
    })();
    return () => { live = false; };
  }, [width, height, master, brand, copy, flipArt]);
  return <><canvas ref={ref} className="preview" />{warn.map((w) => <p key={w} className="warn">{w}</p>)}</>;
}

function Copy({ copy, setCopy, master, brand, opts, setOpts, onNext }) {
  const [size, setSize] = useState(null);
  useEffect(() => { loadImage(master).then((i) => setSize([i.width, i.height])); }, [master]);
  const set = (k) => (e) => setCopy({ ...copy, [k]: e.target.value });
  const rtl = isRtl(copy.headline + copy.sub + copy.cta);
  return (
    <section className="split">
      <div className="stage">{size && <BannerPreview width={size[0]} height={size[1]} master={master} brand={brand} copy={copy} flipArt={opts.flipArt} />}</div>
      <div className="card side" dir="auto">
        <h3>Headline, subtext & CTA</h3>
        <Field label="Headline"><input dir="auto" value={copy.headline} onChange={set('headline')} placeholder="Cold brew, 30% off" /></Field>
        <Field label="Subtext"><textarea dir="auto" rows={2} value={copy.sub} onChange={set('sub')} placeholder="Smooth, bold and ready when you are. This week only." /></Field>
        <Field label="CTA button"><input dir="auto" value={copy.cta} onChange={set('cta')} placeholder="Order now" /></Field>
        {rtl && <p className="note">Persian/RTL copy detected: text is right-aligned and layouts are mirrored.</p>}
        <label className="inline"><input type="checkbox" checked={opts.flipArt} onChange={(e) => setOpts({ ...opts, flipArt: e.target.checked })} />Mirror the artwork (if the empty space is on the wrong side)</label>
        <div className="actions"><button className="primary" disabled={!copy.headline} onClick={onNext}>Choose placements</button></div>
      </div>
    </section>
  );
}

function Placements({ placements, selected, setSelected, addCustom, opts, setOpts, onNext }) {
  const groups = useMemo(() => placements.reduce((g, p) => ((g[p.group || 'Custom'] ||= []).push(p), g), {}), [placements]);
  const toggle = (id) => setSelected(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  const [w, setW] = useState(''); const [h, setH] = useState('');
  const count = placements.filter((p) => selected.includes(p.id)).reduce((n, p) => n + p.sizes.length, 0);
  return (
    <section>
      <h2>Where will this run?</h2>
      <p className="muted">Each placement exports all of its sizes in the platform's format and file-size limit.</p>
      {Object.entries(groups).map(([g, list]) => (
        <div key={g} className="group">
          <h4>{g} <button className="link" onClick={() => setSelected([...new Set([...selected, ...list.map((p) => p.id)])])}>select all</button></h4>
          <div className="placements">
            {list.map((p) => (
              <button key={p.id} className={`placement ${selected.includes(p.id) ? 'picked' : ''}`} onClick={() => toggle(p.id)}>
                <div className="shapes">{p.sizes.map((z) => <i key={z.id} title={`${z.width}×${z.height}`} style={{ aspectRatio: `${z.width}/${z.height}` }} />)}</div>
                <b>{p.name}</b>
                <span>{p.sizes.map((z) => `${z.width}×${z.height}`).join(' · ')}</span>
                <span>{[...new Set(p.sizes.flatMap((z) => z.formats || []))].join('/').toUpperCase()}{p.sizes[0].maxKB && p.sizes[0].maxKB < 10000 ? ` · ≤${p.sizes[0].maxKB} KB` : ''}</span>
                {p.notes && <small>{p.notes}</small>}
              </button>
            ))}
          </div>
        </div>
      ))}
      <div className="actions">
        <label className="inline">Custom size <input className="num" value={w} onChange={(e) => setW(e.target.value)} placeholder="W" />×<input className="num" value={h} onChange={(e) => setH(e.target.value)} placeholder="H" /></label>
        <button disabled={!(+w > 0 && +h > 0)} onClick={() => { addCustom({ id: `custom-${w}x${h}`, name: `Custom ${w}×${h}`, group: 'Custom', sizes: [{ id: `${w}x${h}`, width: +w, height: +h }] }); setW(''); setH(''); }}>Add</button>
        <label className="inline">Format
          <select value={opts.format} onChange={(e) => setOpts({ ...opts, format: e.target.value })}><option value="auto">Platform default</option><option value="jpg">JPG</option><option value="png">PNG</option><option value="webp">WebP</option></select>
        </label>
        <label className="inline"><input type="checkbox" checked={opts.textEverywhere} onChange={(e) => setOpts({ ...opts, textEverywhere: e.target.checked })} />Also put copy on image-only slots</label>
        <button className="primary" disabled={!count} onClick={onNext}>Generate {count || ''} banner{count === 1 ? '' : 's'}</button>
      </div>
    </section>
  );
}

function Results({ results, brief, onRebuild, canRecompose }) {
  const name = slug(brief.business.split(/[,.]/)[0]);
  const items = results.map((r) => ({ ...r, filename: `${r.placement.id}/${name}_${r.placement.id}_${r.size.id === `${r.size.width}x${r.size.height}` ? '' : `${r.size.id}_`}${r.size.width}x${r.size.height}.${r.format}` }));
  return (
    <section>
      <div className="actions top"><h2>Preview</h2><button className="primary" onClick={() => downloadZip(items, `${name}-banners`).catch((e) => { if (e?.code !== 'declined') console.warn(e); })}>Download ZIP ({items.length})</button></div>
      <div className="results">
        {items.map((r) => (
          <figure key={r.key}>
            <div className="frame"><img src={r.url} alt={r.placement.name} style={{ aspectRatio: `${r.size.width}/${r.size.height}` }} /></div>
            <figcaption>
              <b>{r.placement.name}</b>
              <span>{r.size.label ? `${r.size.label} · ` : ''}{r.size.width}×{r.size.height} · {r.format.toUpperCase()} · {r.sizeKB} KB</span>
              <span className="muted">art {r.method}, {r.mode} layout</span>
              {r.warnings.map((w) => <p key={w} className={w.startsWith('Image only') ? 'note' : 'warn'}>{w}</p>)}
              {canRecompose && r.mode !== 'logo' && <button className="link" onClick={() => onRebuild(r)}>Recompose art again</button>}
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}
