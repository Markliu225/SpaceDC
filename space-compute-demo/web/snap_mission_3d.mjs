import { chromium } from 'playwright'
import http from 'node:http'

const OUT = 'C:/Users/markl/AppData/Local/Temp/'
function post(path) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: 'localhost', port: 8001, path, method: 'POST' },
      (res) => { let b=''; res.on('data',c=>{b+=c}); res.on('end',()=>resolve(b)) })
    req.on('error', reject); req.end()
  })
}

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

// Warm up + bind overview camera via /mission, wait for WebRTC stream.
await page.goto('http://localhost:5174/mission', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(38000)

// Make sure idle to start clean, then kick the mission via backend so the
// Kit choreography (overview stage) drives off state.mission.
await post('/mission/stop')
await page.waitForTimeout(1500)
console.log('[snap] start mission:', await post('/mission/start'))

// route phase ~ t=5..9s -> snap at ~7s
await page.waitForTimeout(7000)
await page.screenshot({ path: `${OUT}mission3d-route.png` })
console.log('[snap] saved mission3d-route.png')

// downlink ~ t=12..15s -> snap at ~14s (7s already elapsed)
await page.waitForTimeout(7000)
await page.screenshot({ path: `${OUT}mission3d-downlink.png` })
console.log('[snap] saved mission3d-downlink.png')

await browser.close()
console.log('[snap] done')
