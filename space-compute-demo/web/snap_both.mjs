import { chromium } from 'playwright';

const out = 'C:/Users/markl/AppData/Local/Temp/';
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await ctx.newPage();

console.log('[snap] /satellite');
await page.goto('http://localhost:5173/satellite', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(25000);
await page.screenshot({ path: `${out}final_satellite.png` });
console.log('saved final_satellite.png');

console.log('[snap] / (overview)');
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(18000);
await page.screenshot({ path: `${out}final_overview.png` });
console.log('saved final_overview.png');

await browser.close();
