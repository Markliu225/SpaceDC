import { chromium } from 'playwright';

const out = 'C:/Users/markl/AppData/Local/Temp/';

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

// Warm up by visiting overview first to establish WS
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(6000);

console.log('[snap] nav to /satellite (long wait for MDL compile)');
await page.goto('http://localhost:5173/satellite', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(30000);
await page.screenshot({ path: `${out}snap_satellite_long.png` });
console.log('[snap] saved snap_satellite_long.png');

await browser.close();
console.log('[snap] done');
