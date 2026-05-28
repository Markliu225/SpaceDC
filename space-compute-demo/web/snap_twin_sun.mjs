import { chromium } from 'playwright'
import http from 'node:http'

const OUT = 'C:/Users/markl/AppData/Local/Temp/'

function get(path) {
  return new Promise((resolve, reject) => {
    http.get({ host: 'localhost', port: 8001, path }, (res) => {
      let b = ''; res.on('data', c => { b += c }); res.on('end', () => resolve(JSON.parse(b)))
    }).on('error', reject)
  })
}
function post(path, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body)
    const req = http.request({ host: 'localhost', port: 8001, path, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } },
      (res) => { let b=''; res.on('data',c=>{b+=c}); res.on('end',()=>resolve(b)) })
    req.on('error', reject); req.write(data); req.end()
  })
}

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

// Warm WS, switch to satellite preset.
await page.goto('http://localhost:5174/', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(6000)
await page.goto('http://localhost:5174/satellite', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(35000)  // let WebRTC + Kit stage settle

// Poll backend for a HIGH sun_factor moment, snap.
async function snapAt(label, wantHigh) {
  for (let i = 0; i < 120; i++) {
    const st = await get('/state')
    const sf = st.satellite.sun_factor ?? 0
    const ok = wantHigh ? sf > 0.6 : sf < 0.05
    if (ok) {
      await page.waitForTimeout(1200)   // let Kit's 5Hz poll push the light
      await page.screenshot({ path: `${OUT}twin-sun-${label}.png` })
      console.log(`[snap] ${label}: sun_factor=${sf.toFixed(3)} -> saved`)
      return
    }
    await new Promise(r => setTimeout(r, 1000))
  }
  console.log(`[snap] ${label}: timed out waiting for sun_factor`)
  await page.screenshot({ path: `${OUT}twin-sun-${label}.png` })
}

await snapAt('sunlit', true)
await snapAt('eclipse', false)

await browser.close()
console.log('[snap] done')
