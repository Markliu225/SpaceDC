import { chromium } from 'playwright'
import http from 'node:http'
const OUT = 'C:/Users/markl/AppData/Local/Temp/'

function req(method, path, body) {
  return new Promise((resolve, reject) => {
    const data = body ? Buffer.from(JSON.stringify(body)) : null
    const opts = { host: 'localhost', port: 8001, path, method,
      headers: data ? { 'Content-Type':'application/json','Content-Length': data.length } : {} }
    const r = http.request(opts, x => {
      let b = ''; x.on('data', c => b += c); x.on('end', () => resolve(b))
    })
    r.on('error', reject); if (data) r.write(data); r.end()
  })
}
const phase = async () => JSON.parse(await req('GET', '/state')).mission

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('pageerror', e => console.log('[pe]', e.message.slice(0, 300)))

await page.goto('http://localhost:5174/mission', { waitUntil: 'domcontentloaded' })
let streaming = false
for (let i = 0; i < 120; i++) {
  if (/streaming/i.test(await page.evaluate(() => document.body.innerText))) { streaming = true; break }
  await new Promise(r => setTimeout(r, 1000))
}
console.log('[snap] stream ready =', streaming)
await page.waitForTimeout(4000)

// Start the mission and run through to compute phase to see the silver rack.
await req('POST', '/mission/stop'); await page.waitForTimeout(900)
await req('POST', '/mission/start')

// Watch until phase == compute, then screenshot mid-compute.
let captured = false
for (let i = 0; i < 800 && !captured; i++) {
  const m = await phase()
  if (m.phase === 'compute' && m.phase_progress > 0.3 && m.phase_progress < 0.7) {
    await page.waitForTimeout(150)
    await page.screenshot({ path: OUT + 'gpu-silver-compute.png' })
    await page.screenshot({ path: OUT + 'gpu-silver-compute-vp.png',
      clip: { x: 12, y: 102, width: 928, height: 510 } })
    console.log(`[snap] silver compute frame @ prog=${m.phase_progress.toFixed(2)}`)
    captured = true
  }
  await new Promise(r => setTimeout(r, 100))
}

// Now POST /selection with a GPU card path — exercises backend → WS → web popup.
console.log('[selection] POSTing /selection with /World/ComputeCore/Card_03 ...')
const sel = await req('POST', '/selection', { prim_path: '/World/ComputeCore/Card_03' })
console.log('[selection] backend reply:', sel)
await page.waitForTimeout(1200)
await page.screenshot({ path: OUT + 'gpu-popup.png' })
// Locate the popup card by its width class.
const box = await page.locator('div.w-\\[228px\\].rounded.border.border-border-med').first().boundingBox()
if (box) {
  await page.screenshot({ path: OUT + 'gpu-popup-zoom.png',
    clip: { x: box.x - 6, y: box.y - 6, width: box.width + 12, height: box.height + 12 } })
  console.log('[snap] popup bbox:', box.x.toFixed(0), box.y.toFixed(0), box.width, '×', box.height.toFixed(0))
} else {
  console.log('[snap] popup NOT found in DOM')
}

// Click outside to close (test close behavior).
await page.mouse.click(700, 800)
await page.waitForTimeout(500)
const stillThere = await page.locator('div.w-\\[228px\\].rounded.border.border-border-med').first().boundingBox()
console.log('[snap] after-outside-click popup present =', !!stillThere)

await browser.close()
console.log('[snap] done')
