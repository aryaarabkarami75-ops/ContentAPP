// Builds the no-key, browser-only version of Banner Studio as ONE self-contained HTML body
// (CSS and JS inlined) that can be published as a claude.ai page or hosted as a static file.
import { execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const out = path.join(root, 'client', 'dist-local');
execSync(`npx vite build --base ./ --outDir ${out} --emptyOutDir`, { cwd: path.join(root, 'client'), stdio: 'inherit', env: { ...process.env, VITE_LOCAL: '1' } });
const html = fs.readFileSync(path.join(out, 'index.html'), 'utf8');
const css = [...html.matchAll(/href="\.\/(assets\/[^"]+\.css)"/g)].map((m) => fs.readFileSync(path.join(out, m[1]), 'utf8')).join('\n');
const js = [...html.matchAll(/src="\.\/(assets\/[^"]+\.js)"/g)].map((m) => fs.readFileSync(path.join(out, m[1]), 'utf8')).join('\n');
const page = `<title>Banner Studio</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>${css}</style>
<div id="root"></div>
<script type="module">${js.replace(/<\/script/gi, '<\\/script')}</script>
`;
const dest = process.argv[2] || path.join(root, 'banner-studio-page.html');
fs.writeFileSync(dest, page);
console.log('wrote', dest, Math.round(page.length / 1024), 'KB');
