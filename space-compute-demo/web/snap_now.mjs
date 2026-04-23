import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

await page.goto('http://localhost:5173/satellite', { waitUntil: 'domcontentloaded' });
// Long wait for MDL + stage to settle
await page.waitForTimeout(20000);
await page.screenshot({ path: 'C:/Users/markl/AppData/Local/Temp/snap_now.png' });
console.log('[snap] saved');
await browser.close();
