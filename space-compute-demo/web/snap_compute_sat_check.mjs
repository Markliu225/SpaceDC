import { chromium } from 'playwright'
import http from 'node:http'
const OUT = 'C:/Users/markl/AppData/Local/Temp/'

function req(method, path, body) {
  return new Promise((resolve, reject) => {
    const r = http.request({ host: 'localhost', port: 8001, path, method,
      headers: body ? { 'Content-Type':'application/json' } : {} }, x => {
      let b = ''; x.on('data', c => b += c); x.on('end', () => resolve(b))
    })
    r.on('error', reject); if (body) r.write(JSON.stringify(body)); r.end()
  })
}

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('pageerror', e => console.log('[pe]', e.message.slice(0,250)))

async function waitStream() {
  for (let i = 0; i < 60; i++) {
    if (/streaming/i.test(await page.evaluate(() => document.body.innerText))) return true
    await new Promise(r => setTimeout(r, 1000))
  }
  return false
}

async function setSolar(mat) {
  // Configurator drives /satellite_config — POST it directly to be deterministic.
  await req('POST', '/satellite_config', { solar_material: mat })
  await page.waitForTimeout(3500)   // give Kit a tick to apply the variantSet
}

await page.goto('http://localhost:5174/satellite', { waitUntil: 'domcontentloaded' })
await waitStream()
await page.waitForTimeout(10000)

// 1. Default (Si — blue panels).
await setSolar('Si')
await page.screenshot({ path: OUT + 'check-twin-si.png' })
// Clip just the 3D viewport so it's easier to see.
await page.screenshot({ path: OUT + 'check-twin-si-vp.png',
  clip: { x: 12, y: 70, width: 928, height: 412 } })

// 2. GaAs (magenta).
await setSolar('GaAs')
await page.screenshot({ path: OUT + 'check-twin-gaas-vp.png',
  clip: { x: 12, y: 70, width: 928, height: 412 } })

// 3. Perovskite (pink).
await setSolar('Perovskite')
await page.screenshot({ path: OUT + 'check-twin-perovskite-vp.png',
  clip: { x: 12, y: 70, width: 928, height: 412 } })

// 4. HUD at bottom-left should still be there.
const box = await page.locator('div.relative.h-\\[200px\\].w-\\[180px\\]').first().boundingBox()
if (box) {
  await page.screenshot({ path: OUT + 'check-twin-hud.png',
    clip: { x: box.x - 4, y: box.y - 4, width: box.width + 8, height: box.height + 8 } })
  console.log('[snap] hud bbox ok:', box.x.toFixed(0), box.y.toFixed(0))
} else { console.log('[snap] HUD bbox not found') }

// 5. Overview unaffected.
await page.getByRole('link', { name: 'Overview' }).click()
await page.waitForTimeout(7000)
await page.screenshot({ path: OUT + 'check-overview.png' })

await browser.close()
console.log('[snap] done')
