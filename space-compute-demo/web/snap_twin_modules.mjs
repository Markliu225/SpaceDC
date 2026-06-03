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
page.on('pageerror', e => console.log('[pe]', e.message.slice(0, 300)))

await page.goto('http://localhost:5174/satellite', { waitUntil: 'domcontentloaded' })
let streaming = false
for (let i = 0; i < 90; i++) {
  if (/streaming/i.test(await page.evaluate(() => document.body.innerText))) { streaming = true; break }
  await new Promise(r => setTimeout(r, 1000))
}
console.log('[snap] stream ready =', streaming)
await page.waitForTimeout(12000)

await page.screenshot({ path: OUT + 'twin-body-full.png' })
await page.screenshot({ path: OUT + 'twin-body-vp.png',
  clip: { x: 12, y: 70, width: 928, height: 480 } })
console.log('[snap] no-selection vp captured')

async function clickPrim(name, primPath) {
  const r = await req('POST', '/selection', { prim_path: primPath })
  console.log(`[${name}] /selection -> ${r}`)
  await page.waitForTimeout(1300)
  await page.screenshot({ path: OUT + `twin-popup-${name}-full.png` })
  // Locate the popup card and clip a tight crop.
  const box = await page.locator('div.w-\\[228px\\].rounded.border.border-border-med').first().boundingBox()
  if (box) {
    await page.screenshot({ path: OUT + `twin-popup-${name}.png`,
      clip: { x: box.x - 6, y: box.y - 6, width: box.width + 12, height: box.height + 12 } })
    console.log(`[${name}] popup bbox: ${box.x.toFixed(0)},${box.y.toFixed(0)} ${box.width}x${box.height.toFixed(0)}`)
  } else {
    console.log(`[${name}] POPUP NOT FOUND in DOM`)
  }
}

await clickPrim('shell', '/World/Satellite/Bus/ParentNode/tripo_part_9/Mesh_0')
await clickPrim('radar', '/World/Satellite/Bus/ParentNode/tripo_part_4/Mesh_4')
await clickPrim('gpu13', '/World/Satellite/Bus/ParentNode/tripo_part_13/Mesh_2')
await clickPrim('gpu11', '/World/Satellite/Bus/ParentNode/tripo_part_11/Mesh_7')

// Clear and verify it closes.
await req('POST', '/selection', { prim_path: '' })
await page.waitForTimeout(800)
const stillThere = await page.locator('div.w-\\[228px\\].rounded.border.border-border-med').first().boundingBox()
console.log('[clear] popup present after clear =', !!stillThere)

await browser.close()
console.log('[snap] done')
