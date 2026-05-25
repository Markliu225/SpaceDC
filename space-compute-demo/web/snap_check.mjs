import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

await page.goto('http://localhost:5173/satellite', { waitUntil: 'load' });
await page.waitForTimeout(40000);
await page.screenshot({ path: 'C:/Users/markl/AppData/Local/Temp/snap_check.png' });
console.log('[snap] satellite saved');
await browser.close();
