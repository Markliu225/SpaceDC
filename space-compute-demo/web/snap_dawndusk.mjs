// Verify the dawn-dusk orbit: screenshot the FallbackEarth canvas directly
// (bypasses the stream-slot overlay). Headful + GPU so Bloom renders.
import { chromium } from 'playwright'
const OUT = process.argv[2] || 'C:/Users/markl/AppData/Local/Temp/overview.png'
const browser = await chromium.launch({
  headless: false,
  args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist', '--window-size=1320,940'],
})
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage()
page.on('pageerror', (e) => console.error('[pageerror]', e.message))
await page.goto('http://localhost:5174/', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(13000)
// pick the largest canvas (the FallbackEarth viewport) and grab its pixels
const info = await page.evaluate(() => {
  const cs = [...document.querySelectorAll('canvas')]
  let best = null, area = 0
  for (const c of cs) { const a = c.width * c.height; if (a > area) { area = a; best = c } }
  if (!best) return { found: false }
  return { found: true, w: best.width, h: best.height, data: best.toDataURL('image/png') }
})
console.log('[canvas]', info.found, info.w, 'x', info.h)
if (info.found) {
  const b64 = info.data.split(',')[1]
  const fs = await import('node:fs')
  fs.writeFileSync(OUT, Buffer.from(b64, 'base64'))
  console.log('[snap] canvas saved', OUT)
}
await browser.close()
