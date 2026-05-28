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
await page.waitForTimeout(38000)

await req('POST', '/mission/stop')
await page.waitForTimeout(800)
await req('POST', '/mission/start')

// Capture one frame in each of the four camera shots.
const shots = [
  { want: 'capture',  lo: 0.3, hi: 0.8, label: 'capture' },
  { want: 'route',    lo: 0.4, hi: 0.7, label: 'route' },
  { want: 'compute',  lo: 0.4, hi: 0.7, label: 'compute' },
  { want: 'downlink', lo: 0.3, hi: 0.7, label: 'downlink' },
]
let si = 0
for (let i = 0; i < 400 && si < shots.length; i++) {
  const m = await phase()
  const s = shots[si]
  if (m.phase === s.want && m.phase_progress >= s.lo && m.phase_progress <= s.hi) {
    await page.waitForTimeout(200)
    await page.screenshot({ path: `${OUT}cam-${s.label}.png` })
    console.log(`[snap] cam-${s.label}: phase=${m.phase} prog=${m.phase_progress.toFixed(2)} sensor=${m.sensor_idx} hub=${m.hub_idx}`)
    si++
  }
  await new Promise(r => setTimeout(r, 100))
}
await browser.close()
console.log('[snap] done')
