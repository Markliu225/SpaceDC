import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

// Navigate DIRECTLY to /interior — page mount sends preset=interior, then
// StreamMount establishes WebRTC. We give it long enough for both.
await page.goto('http://localhost:5173/interior', { waitUntil: 'load' });

// Wait for stream to be 'ready' (StreamMount marks it ready after handshake).
// Wait for the <video> element to start receiving frames AND for Kit to
// finish loading the new stage. Polling check on the video's currentTime
// — once it advances, frames are arriving.
await page.waitForFunction(() => {
    const v = document.querySelector('video');
    return v && v.videoWidth > 100;
}, { timeout: 60000 }).catch(() => console.log('[warn] video element not detected in time'));

// Then wait further for MDL shaders + camera bind to settle.
await page.waitForTimeout(50000);

// Force a focus event on the video so Kit's WebRTC subsystem keeps streaming
await page.evaluate(() => {
    const v = document.querySelector('video');
    if (v) { v.focus(); v.play().catch(()=>{}); }
});
await page.waitForTimeout(5000);

await page.screenshot({ path: 'C:/Users/markl/AppData/Local/Temp/snap_now.png' });
console.log('[snap] interior saved');
await browser.close();
