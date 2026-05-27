import { chromium } from 'playwright'
import http from 'node:http'

const OUT = 'C:/Users/markl/AppData/Local/Temp/'

function post(path, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body)
    const req = http.request({
      host: 'localhost', port: 8001, path, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
    }, (res) => { let buf = ''; res.on('data', c => { buf += c }); res.on('end', () => resolve(buf)) })
    req.on('error', reject); req.write(data); req.end()
  })
}

const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'],
})
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()

await page.goto('http://localhost:5174/', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(8000)
await page.goto('http://localhost:5174/satellite', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(40000)

const mats = ['Si', 'GaAs', 'Perovskite']
for (const m of mats) {
  console.log(`[snap] -> ${m}`)
  console.log(await post('/satellite_config', {
    gpu: 'H100', solar_size: 'L', solar_material: m,
    radiator_size: 'Standard', radiator_material: 'Aluminum',
  }))
  await page.waitForTimeout(5000)
  await page.screenshot({ path: `${OUT}twin-mat-${m}.png` })
  console.log(`[snap] saved twin-mat-${m}.png`)
}

await browser.close()
