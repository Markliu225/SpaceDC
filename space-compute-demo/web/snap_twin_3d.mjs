import { chromium } from 'playwright'
import http from 'node:http'

const OUT_DIR = 'C:/Users/markl/AppData/Local/Temp/'

function post(path, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body)
    const req = http.request({
      host: 'localhost', port: 8001, path, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
    }, (res) => {
      let buf = ''
      res.on('data', (c) => { buf += c })
      res.on('end', () => resolve(buf))
    })
    req.on('error', reject)
    req.write(data)
    req.end()
  })
}

const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'],
})
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()
page.on('pageerror', (e) => console.error('[pageerror]', e.message))
page.on('console', (m) => { if (m.type() === 'error') console.error('[console]', m.text()) })

// Reset to baseline before snapping.
console.log('[snap] reset to baseline')
console.log(await post('/satellite_config', {
  gpu: 'H100', solar_size: 'M', solar_material: 'Si',
  radiator_size: 'Standard', radiator_material: 'Aluminum',
}))

console.log('[snap] warm up via /')
await page.goto('http://localhost:5174/', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(8000)

console.log('[snap] nav to /satellite — wait for WebRTC')
await page.goto('http://localhost:5174/satellite', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(40000)

await page.screenshot({ path: `${OUT_DIR}twin-baseline.png`, fullPage: false })
console.log('[snap] baseline.png saved')

// Trigger a config swap.
console.log('[snap] POST B200/XL/Perovskite/Wide/Graphite')
console.log(await post('/satellite_config', {
  gpu: 'B200', solar_size: 'XL', solar_material: 'Perovskite',
  radiator_size: 'Wide', radiator_material: 'Graphite',
}))

await page.waitForTimeout(6000)
await page.screenshot({ path: `${OUT_DIR}twin-b200.png`, fullPage: false })
console.log('[snap] b200.png saved')

await browser.close()
console.log('[snap] done')
