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

// Wait until the WebRTC stream chip reads "streaming" (DOM text), up to 120s.
let streaming = false
for (let i = 0; i < 120; i++) {
  const txt = await page.evaluate(() => document.body.innerText)
  if (/streaming/i.test(txt)) { streaming = true; break }
  await new Promise(r => setTimeout(r, 1000))
}
console.log('[snap] stream ready =', streaming)
// The AECO city scene streams its geometry from S3 (~27-30s after the
// mission stage opens). Wait it out so acquire shows the full city, not
// an empty tile, before the capture-shrink begins.
await page.waitForTimeout(38000)

await req('POST', '/mission/stop')
await page.waitForTimeout(900)
await req('POST', '/mission/start')

// The capture phase (6s) sub-beats: establish → sweep → collapse → fly-to-sat.
const shots = [
  { want: 'acquire', lo: 0.4, hi: 0.9, label: 'cap0-establish' },
  { want: 'capture', lo: 0.25, hi: 0.42, label: 'cap1-sweep' },
  { want: 'capture', lo: 0.55, hi: 0.66, label: 'cap2-collapse' },
  { want: 'capture', lo: 0.74, hi: 0.84, label: 'cap3-cube' },
  { want: 'capture', lo: 0.90, hi: 0.99, label: 'cap4-tosat' },
]
let si = 0
for (let i = 0; i < 1200 && si < shots.length; i++) {
  const m = await phase()
  const s = shots[si]
  if (m.phase === s.want && m.phase_progress >= s.lo && m.phase_progress <= s.hi) {
    await page.waitForTimeout(110)
    await page.screenshot({ path: `${OUT}${s.label}.png` })
    console.log(`[snap] ${s.label}: phase=${m.phase} prog=${m.phase_progress.toFixed(2)}`)
    si++
  }
  await new Promise(r => setTimeout(r, 55))
}
await browser.close()
console.log('[snap] done', si, '/', shots.length)
