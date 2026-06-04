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
const phase = async () => JSON.parse(await req('GET', '/state')).mission

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.goto('http://localhost:5174/mission', { waitUntil: 'domcontentloaded' })

let streaming = false
for (let i = 0; i < 120; i++) {
  const txt = await page.evaluate(() => document.body.innerText)
  if (/streaming/i.test(txt)) { streaming = true; break }
  await new Promise(r => setTimeout(r, 1000))
}
console.log('[snap] stream ready =', streaming)
await page.waitForTimeout(40000)   // preload the heavy local city into GPU

await req('POST', '/mission/stop')
await page.waitForTimeout(900)
await req('POST', '/mission/start')

// One frame at the midpoint of each phase, in a single mission run.
const want = ['acquire', 'capture', 'route', 'compute', 'downlink', 'deliver']
let wi = 0
for (let i = 0; i < 2000 && wi < want.length; i++) {
  const m = await phase()
  if (m.phase === want[wi] && m.phase_progress >= 0.45 && m.phase_progress <= 0.7) {
    await page.waitForTimeout(120)
    await page.screenshot({ path: `${OUT}ph-${wi}-${want[wi]}.png` })
    console.log(`[snap] ph-${wi}-${want[wi]}: prog=${m.phase_progress.toFixed(2)}`)
    wi++
  }
  await new Promise(r => setTimeout(r, 45))
}
await browser.close()
console.log('[snap] done', wi, '/', want.length)
