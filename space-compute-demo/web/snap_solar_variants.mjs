import { chromium } from 'playwright'
import http from 'node:http'
const OUT = 'C:/Users/markl/AppData/Local/Temp/'

function req(method, path, body) {
  return new Promise((resolve, reject) => {
    const data = body ? Buffer.from(JSON.stringify(body)) : null
    const opts = { host: 'localhost', port: 8001, path, method,
      headers: data ? { 'Content-Type': 'application/json', 'Content-Length': data.length } : {} }
    const r = http.request(opts, x => { let b = ''; x.on('data', c => b += c); x.on('end', () => resolve(b)) })
    r.on('error', reject); if (data) r.write(data); r.end()
  })
}

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('pageerror', e => console.log('[pe]', e.message.slice(0, 250)))

await page.goto('http://localhost:5174/satellite', { waitUntil: 'domcontentloaded' })
for (let i = 0; i < 90; i++) {
  if (/streaming/i.test(await page.evaluate(() => document.body.innerText))) break
  await new Promise(r => setTimeout(r, 1000))
}
await page.waitForTimeout(12000)

// 1) Cycle through every solar_size, snap the 3D viewport — proves the
//    visual panel actually changes shape when the variant flips.
for (const sz of ['S', 'M', 'L', 'XL']) {
  console.log(`>> solar_size = ${sz}`)
  await req('POST', '/satellite_config', { solar_size: sz })
  await page.waitForTimeout(5000)
  await page.screenshot({ path: OUT + `solar-size-${sz}-vp.png`,
    clip: { x: 12, y: 70, width: 928, height: 480 } })
}

// 2) Click a solar panel — proves the popup wires up.
await req('POST', '/selection', { prim_path: '/World/Satellite/Bus/PanelLeft' })
await page.waitForTimeout(1300)
const box = await page.locator('div.w-\\[228px\\].rounded.border.border-border-med').first().boundingBox()
if (box) {
  await page.screenshot({ path: OUT + 'solar-popup-left.png',
    clip: { x: box.x - 6, y: box.y - 6, width: box.width + 12, height: box.height + 12 } })
  console.log('[solar popup] bbox:', box.x.toFixed(0), box.y.toFixed(0), box.width, '×', box.height.toFixed(0))
} else { console.log('[solar popup] NOT FOUND') }
await req('POST', '/selection', { prim_path: '' })

// 3) Snap the configurator right rail — proves the cryptic delta block is
//    gone and the new Design summary card is visible.
await page.waitForTimeout(800)
await page.screenshot({ path: OUT + 'twin-configurator-rail.png',
  clip: { x: 944, y: 70, width: 480, height: 800 } })

await browser.close()
console.log('done')
