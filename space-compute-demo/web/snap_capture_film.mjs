import { chromium } from 'playwright'
import http from 'node:http'

const OUT = 'C:/Users/markl/AppData/Local/Temp/film/'
import fs from 'node:fs'
fs.mkdirSync(OUT, { recursive: true })
for (const f of fs.readdirSync(OUT)) fs.rmSync(OUT + f)

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

async function waitStreaming(s) {
  for (let i = 0; i < s; i++) {
    const txt = await page.evaluate(() => document.body.innerText)
    if (/streaming/i.test(txt)) return true
    await new Promise(r => setTimeout(r, 1000))
  }
  return false
}
let streaming = false
for (let a = 0; a < 4 && !streaming; a++) {
  if (a > 0) { console.log('[film] reload', a + 1); await page.reload({ waitUntil: 'domcontentloaded' }) }
  streaming = await waitStreaming(30)
}
console.log('[film] streaming =', streaming)
if (!streaming) { await browser.close(); process.exit(2) }

await page.waitForTimeout(30000)   // idle: preload the city
await req('POST', '/mission/stop'); await page.waitForTimeout(1000)
await req('POST', '/mission/start')

// Rapid-fire frames through acquire+capture+route (~13s). Label each with the
// backend phase/progress at grab time (render lags ~1.5s, reviewer accounts).
// capture is ~30s, so film well past it (acquire 3 + capture 30 + route).
const t0 = Date.now()
let n = 0
while (Date.now() - t0 < 38000) {
  const m = await phase()
  const tag = `${String(n).padStart(3, '0')}_${m.phase}_${m.phase_progress.toFixed(2)}`
  await page.screenshot({ path: `${OUT}f${tag}.png` })
  n++
  await new Promise(r => setTimeout(r, 450))
}
await browser.close()
console.log('[film] done', n, 'frames ->', OUT)
