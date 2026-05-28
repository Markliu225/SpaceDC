import { chromium } from 'playwright'
import http from 'node:http'
const OUT = 'C:/Users/markl/AppData/Local/Temp/'
function req(m, p) {
  return new Promise((res, rej) => {
    const r = http.request({ host: 'localhost', port: 8001, path: p, method: m }, x => {
      let b = ''; x.on('data', c => b += c); x.on('end', () => res(b))
    }); r.on('error', rej); r.end()
  })
}
const ph = async () => JSON.parse(await req('GET', '/state')).mission
const br = await chromium.launch({ headless: true })
const pg = await br.newPage({ viewport: { width: 1440, height: 900 } })
await pg.goto('http://localhost:5174/mission', { waitUntil: 'domcontentloaded' })
await pg.waitForTimeout(36000)
await req('POST', '/mission/stop'); await pg.waitForTimeout(700); await req('POST', '/mission/start')
const got = { dl: false, dv: false }
for (let i = 0; i < 400; i++) {
  const m = await ph()
  if (!got.dl && m.phase === 'downlink' && m.phase_progress > 0.8) {
    await pg.waitForTimeout(150); await pg.screenshot({ path: OUT + 'cam-downlink-late.png' })
    console.log('downlink-late', m.phase_progress.toFixed(2)); got.dl = true
  }
  if (!got.dv && m.phase === 'deliver' && m.phase_progress > 0.4) {
    await pg.waitForTimeout(150); await pg.screenshot({ path: OUT + 'cam-deliver.png' })
    console.log('deliver', m.phase_progress.toFixed(2)); got.dv = true
  }
  if (got.dl && got.dv) break
  await new Promise(r => setTimeout(r, 90))
}
await br.close(); console.log('done')
