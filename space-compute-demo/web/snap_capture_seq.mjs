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

// Wait until the WebRTC stream chip reads "streaming". The handshake is
// occasionally flaky, so reload and retry a few times if it stays
// "connecting…".
async function waitStreaming(perTryS) {
  for (let i = 0; i < perTryS; i++) {
    const txt = await page.evaluate(() => document.body.innerText)
    if (/streaming/i.test(txt)) return true
    await new Promise(r => setTimeout(r, 1000))
  }
  return false
}
let streaming = false
for (let attempt = 0; attempt < 4 && !streaming; attempt++) {
  if (attempt > 0) {
    console.log('[snap] stream stuck — reloading (attempt', attempt + 1, ')')
    await page.reload({ waitUntil: 'domcontentloaded' })
  }
  streaming = await waitStreaming(30)
}
console.log('[snap] stream ready =', streaming)
if (!streaming) { console.log('[snap] ABORT: no stream'); await browser.close(); process.exit(2) }
// First-run preload test: just sit idle a while. The driver parks the city
// at sub-pixel scale during idle so the renderer loads it; then a single
// Start should pop the full city on the very first capture.
await page.waitForTimeout(30000)
await page.screenshot({ path: `${OUT}cap-idle.png` })   // idle framing check
console.log('[snap] cap-idle captured')
await req('POST', '/mission/start')

// The capture phase (6s) sub-beats: establish → sweep → collapse → fly-to-sat.
// NOTE: the rendered WebRTC frame lags backend /state by ~0.3-0.5s, so detect
// a little early and settle ~500ms before the shot to let the render catch up.
const shots = [
  { want: 'acquire', lo: 0.3, hi: 0.8, label: 'cap0-establish' },
  { want: 'capture', lo: 0.15, hi: 0.35, label: 'cap1-sweep' },
  { want: 'capture', lo: 0.45, hi: 0.58, label: 'cap2-collapse' },
  { want: 'capture', lo: 0.66, hi: 0.78, label: 'cap3-cube' },
  { want: 'capture', lo: 0.86, hi: 0.96, label: 'cap4-tosat' },
  { want: 'route',   lo: 0.02, hi: 0.20, label: 'cap5-docked' },
]
let si = 0
for (let i = 0; i < 1600 && si < shots.length; i++) {
  const m = await phase()
  const s = shots[si]
  if (m.phase === s.want && m.phase_progress >= s.lo && m.phase_progress <= s.hi) {
    await page.waitForTimeout(480)
    await page.screenshot({ path: `${OUT}${s.label}.png` })
    console.log(`[snap] ${s.label}: phase=${m.phase} prog=${m.phase_progress.toFixed(2)}`)
    si++
  }
  await new Promise(r => setTimeout(r, 55))
}
await browser.close()
console.log('[snap] done', si, '/', shots.length)
