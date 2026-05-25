import { chromium } from 'playwright';
import { promises as fs } from 'node:fs';

const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'],
});
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1.5,
});
const page = await ctx.newPage();
page.on('pageerror', (err) => console.error('[pageerror]', err.message));

await page.goto('http://localhost:5174/', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(8000);

const m = await page.evaluate(() => {
  const html = document.documentElement;
  const main = document.querySelector('.shell__main');
  return {
    viewport:   { w: window.innerWidth, h: window.innerHeight },
    overflowY:  html.scrollHeight > html.clientHeight,
    overflowX:  html.scrollWidth  > html.clientWidth,
    mainSize:   main ? { scrollH: main.scrollHeight, clientH: main.clientHeight } : null,
  };
});
console.log('[measure]', JSON.stringify(m));

const compositeB64 = await page.evaluate(async () => {
  const out = document.createElement('canvas');
  out.width = window.innerWidth;
  out.height = window.innerHeight;
  const octx = out.getContext('2d');
  octx.fillStyle = '#060912';
  octx.fillRect(0, 0, out.width, out.height);
  const gl = document.querySelector('canvas');
  if (gl) {
    const r = gl.getBoundingClientRect();
    octx.drawImage(gl, r.left, r.top, r.width, r.height);
  }
  return out.toDataURL('image/png');
});
await fs.writeFile(
  'C:/Users/markl/AppData/Local/Temp/overview-webgl-only.png',
  Buffer.from(compositeB64.replace(/^data:image\/png;base64,/, ''), 'base64'),
);

await page.screenshot({ path: 'C:/Users/markl/AppData/Local/Temp/overview-shot.png', fullPage: false });

await browser.close();
