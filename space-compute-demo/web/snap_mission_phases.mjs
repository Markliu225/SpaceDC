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
const getPhase = async () => {
  const d = JSON.parse(await req('GET', '/state'))
  return d.mission
}

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.goto('http://localhost:5174/mission', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(38000)

async function snapDuringPhase(want, label) {
  await req('POST', '/mission/stop')
  await page.waitForTimeout(800)
  await req('POST', '/mission/start')
  // Poll until the desired phase, snap at its midpoint.
  for (let i = 0; i < 220; i++) {
    const m = await getPhase()
    if (m.phase === want && m.phase_progress > 0.35 && m.phase_progress < 0.7) {
      await page.waitForTimeout(250)
      const crop = OUT + `mission-${label}.png`
      await page.screenshot({ path: crop })
      console.log(`[snap] ${label}: phase=${m.phase} prog=${m.phase_progress.toFixed(2)} sensor=${m.sensor_idx} hub=${m.hub_idx}`)
      return
    }
    await new Promise(r => setTimeout(r, 120))
  }
  console.log(`[snap] ${label}: timed out`)
}

await snapDuringPhase('route', 'route')
await snapDuringPhase('downlink', 'downlink')
await browser.close()
console.log('[snap] done')
