import { chromium } from 'playwright';
import { promises as fs } from 'node:fs';

const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'],
});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
page.on('pageerror', (err) => console.error('[pageerror]', err.message));

await page.goto('http://localhost:5174/', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(15000);

// Composite: paint the canvas onto a 2d buffer that's the same size as the
// viewport, positioned where the canvas lives. Then base64 → file.
const compositeB64 = await page.evaluate(async () => {
  const out = document.createElement('canvas');
  out.width = window.innerWidth;
  out.height = document.documentElement.scrollHeight;
  const octx = out.getContext('2d');

  // Walk DOM, snapshot each card via html2canvas-like fallback: simpler path —
  // first paint a CSS background, then overlay the WebGL canvas.
  octx.fillStyle = '#060912';
  octx.fillRect(0, 0, out.width, out.height);

  // Overlay the WebGL canvas at its DOM position.
  const gl = document.querySelector('canvas');
  if (gl) {
    const r = gl.getBoundingClientRect();
    octx.drawImage(gl, r.left + window.scrollX, r.top + window.scrollY, r.width, r.height);
  }
  return out.toDataURL('image/png');
});

// Save the composite WebGL-only image; useful for verifying the Three scene works.
const webglOnly = compositeB64.replace(/^data:image\/png;base64,/, '');
await fs.writeFile('C:/Users/markl/AppData/Local/Temp/overview-webgl-only.png', Buffer.from(webglOnly, 'base64'));
console.log('[snap] webgl-only saved');

// Also take the standard page screenshot (DOM/UI only, WebGL likely missing in headless).
await page.screenshot({ path: 'C:/Users/markl/AppData/Local/Temp/overview-shot.png', fullPage: true });
console.log('[snap] full saved');

await browser.close();
