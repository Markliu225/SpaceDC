import { chromium } from 'playwright'
const OUT = 'C:/Users/markl/AppData/Local/Temp/'
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

await page.goto('http://localhost:5174/satellite', { waitUntil: 'domcontentloaded' })
// Stream connect (10-20s) then a beat for the HUD canvas to render.
for (let i = 0; i < 60; i++) {
  if (/streaming/i.test(await page.evaluate(() => document.body.innerText))) {
    console.log('twin streaming'); break
  }
  await new Promise(r => setTimeout(r, 1000))
}
await page.waitForTimeout(8000)
await page.screenshot({ path: OUT + 'twin-hud.png' })
console.log('[snap] twin-hud captured')

// Tight crop of the HUD itself for readability.
await page.locator('.absolute.right-3.top-3.z-10').first().screenshot({ path: OUT + 'twin-hud-zoom.png' })
console.log('[snap] twin-hud-zoom captured')

// Verify Overview still renders correctly (nothing broken).
await page.getByRole('link', { name: 'Overview' }).click()
await page.waitForTimeout(7000)
await page.screenshot({ path: OUT + 'overview-after-hud.png' })
console.log('[snap] overview-after-hud captured')

await browser.close()
console.log('[snap] done')
