import { chromium } from 'playwright';

const out = 'C:/Users/markl/AppData/Local/Temp/';

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

page.on('pageerror', (e) => console.log('[pageerror]', e.message));

async function snap(path, file, waitMs) {
  console.log(`[snap] goto ${path}`);
  await page.goto(`http://localhost:5173${path}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(waitMs);
  await page.screenshot({ path: `${out}${file}`, fullPage: false });
  console.log(`[snap] saved ${file}`);
}

await snap('/', 'snap_overview.png', 10000);
await snap('/satellite', 'snap_satellite.png', 12000);
await snap('/', 'snap_overview_after.png', 10000);

await browser.close();
console.log('[snap] done');
