import { chromium } from 'playwright'
const OUT = 'C:/Users/markl/AppData/Local/Temp/'
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

page.on('console', m => { if (m.type() === 'error' || m.type() === 'warn') console.log('[page', m.type(), ']', m.text().slice(0,400)) })
page.on('pageerror', e => console.log('[pageerror]', e.message.slice(0,400)))
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
// Generous clip around the bottom-left of the viewport cell.
await page.screenshot({ path: OUT + 'twin-hud-zoom.png',
  clip: { x: 20, y: 300, width: 230, height: 260 } })
console.log('[snap] twin-hud-zoom captured')

// Verify Overview still renders correctly (nothing broken).
await page.getByRole('link', { name: 'Overview' }).click()
await page.waitForTimeout(7000)
await page.screenshot({ path: OUT + 'overview-after-hud.png' })
console.log('[snap] overview-after-hud captured')

await browser.close()
console.log('[snap] done')
