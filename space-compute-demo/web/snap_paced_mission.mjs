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
const mission = async () => JSON.parse(await req('GET', '/state')).mission

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.goto('http://localhost:5174/mission', { waitUntil: 'domcontentloaded' })
let streaming = false
for (let i = 0; i < 120; i++) {
  if (/streaming/i.test(await page.evaluate(() => document.body.innerText))) { streaming = true; break }
  await new Promise(r => setTimeout(r, 1000))
}
console.log('[paced] stream ready =', streaming)
await page.waitForTimeout(2500)

const t0 = Date.now()
await req('POST', '/mission/stop'); await new Promise(r => setTimeout(r, 800))
await req('POST', '/mission/start')
console.log('[paced] start posted')

// capture sweep frames across the long capture phase + collapse/cube.
const shots = [
  { want: 'acquire', lo: 0.0,  hi: 0.5,  label: 'p0-acquire' },
  { want: 'capture', lo: 0.12, hi: 0.22, label: 'p1-sweepA' },
  { want: 'capture', lo: 0.40, hi: 0.50, label: 'p2-sweepB' },
  { want: 'capture', lo: 0.70, hi: 0.78, label: 'p3-sweepC' },
  { want: 'capture', lo: 0.86, hi: 0.92, label: 'p4-collapse' },
  { want: 'capture', lo: 0.965,hi: 0.995,label: 'p5-cube' },
  { want: 'route',   lo: 0.30, hi: 0.55, label: 'p6-route' },
]
let si = 0
let lastLog = ''
for (let i = 0; i < 3000 && si < shots.length; i++) {
  const m = await mission()
  const tag = `${m.phase}/${m.phase_progress.toFixed(2)}`
  if (tag !== lastLog && (m.phase === 'acquire' || Math.random() < 0.15)) {
    console.log(`[t+${((Date.now()-t0)/1000).toFixed(1)}s] ${tag} active=${m.active}`)
    lastLog = tag
  }
  const s = shots[si]
  if (m.phase === s.want && m.phase_progress >= s.lo && m.phase_progress <= s.hi) {
    await page.waitForTimeout(110)
    await page.screenshot({ path: `${OUT}${s.label}.png` })
    console.log(`[snap] ${s.label}: ${tag}`)
    si++
  }
  await new Promise(r => setTimeout(r, 80))
}
await browser.close()
console.log('[paced] done', si, '/', shots.length)
