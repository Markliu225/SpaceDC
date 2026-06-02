import { chromium } from 'playwright'
import http from 'node:http'
const OUT = 'C:/Users/markl/AppData/Local/Temp/'

function req(method, path) {
  return new Promise((resolve, reject) => {
    const r = http.request({ host: 'localhost', port: 8001, path, method }, (res) => {
      let b = ''; res.on('data', c => { b += c }); res.on('end', () => resolve(b))
    }); r.on('error', reject); r.end()
  })
}

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('pageerror', e => console.log('[pageerror]', e.message.slice(0, 300)))

async function snapHud(label) {
  // Find the HUD card by its 180px width and grab its bbox precisely.
  const box = await page.locator('div.relative.h-\\[200px\\].w-\\[180px\\]').first().boundingBox()
  if (!box) { console.log(label, 'HUD box not found'); return }
  await page.screenshot({ path: `${OUT}twin-hud-${label}.png`,
    clip: { x: box.x - 4, y: box.y - 4, width: box.width + 8, height: box.height + 8 } })
  console.log('[snap]', label, `hud bbox: ${box.x.toFixed(0)},${box.y.toFixed(0)} ${box.width}×${box.height}`)
}

async function setConstellation(id) {
  await req('POST', `/constellation/${id}`)
  await page.waitForTimeout(2500)
}

async function waitStream() {
  for (let i = 0; i < 60; i++) {
    if (/streaming/i.test(await page.evaluate(() => document.body.innerText))) return true
    await new Promise(r => setTimeout(r, 1000))
  }
  return false
}

// Visit Overview first so a constellation is loaded into the shared store.
await page.goto('http://localhost:5174/', { waitUntil: 'domcontentloaded' })
await waitStream()
await page.waitForTimeout(2500)

// Test #1: Iridium NEXT — 6 planes × 11 sats. HUD should show 6 rings.
await setConstellation('iridium_next')
await page.getByRole('link', { name: 'Satellite Twin' }).click()
await page.waitForTimeout(6000)
await page.screenshot({ path: OUT + 'twin-full-iridium.png' })
await snapHud('iridium')

// Test #2: OneWeb — 18 planes × 36 sats. HUD should show 18 rings.
await page.getByRole('link', { name: 'Overview' }).click()
await page.waitForTimeout(1500)
await setConstellation('oneweb')
await page.getByRole('link', { name: 'Satellite Twin' }).click()
await page.waitForTimeout(6000)
await page.screenshot({ path: OUT + 'twin-full-oneweb.png' })
await snapHud('oneweb')

// Test #3: single_iss — 1 plane × 1 sat. HUD should show just 1 ring.
await page.getByRole('link', { name: 'Overview' }).click()
await page.waitForTimeout(1500)
await setConstellation('single_iss')
await page.getByRole('link', { name: 'Satellite Twin' }).click()
await page.waitForTimeout(6000)
await snapHud('iss')

// Test #4: Overview unaffected.
await page.getByRole('link', { name: 'Overview' }).click()
await page.waitForTimeout(6000)
await page.screenshot({ path: OUT + 'overview-after-hud.png' })

await browser.close()
console.log('[snap] done')
