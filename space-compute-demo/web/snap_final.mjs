import { chromium } from 'playwright';

const out = 'C:/Users/markl/AppData/Local/Temp/';

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

// Overview first
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(20000);
await page.screenshot({ path: `${out}snap_final_overview.png` });
console.log('[snap] overview saved');

// Now satellite (large wait for stage swap + MDL)
await page.goto('http://localhost:5173/satellite', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(25000);
await page.screenshot({ path: `${out}snap_final_satellite.png` });
console.log('[snap] satellite saved');

await browser.close();
