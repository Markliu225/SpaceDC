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
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

// 1. Mission page — wait for stream, run a mission through to delivery.
await page.goto('http://localhost:5174/mission', { waitUntil: 'domcontentloaded' })
let streaming = false
for (let i = 0; i < 120; i++) {
  if (/streaming/i.test(await page.evaluate(() => document.body.innerText))) { streaming = true; break }
  await new Promise(r => setTimeout(r, 1000))
}
console.log('[repro] mission stream ready =', streaming)
await page.waitForTimeout(3000)
await req('POST', '/mission/start')
await page.waitForTimeout(26000)   // run to delivered (hero cam at the dish)

// 2. CLIENT-SIDE nav to Overview (the in-app tab, WS stays open).
await page.getByRole('link', { name: 'Overview' }).click()
console.log('[repro] clicked Overview tab')
await page.waitForTimeout(8000)
await page.screenshot({ path: OUT + 'repro-ovv-clientnav.png' })
console.log('[repro] preset after click =', JSON.parse(await req('GET', '/state')).camera_preset)
await page.waitForTimeout(8000)
await page.screenshot({ path: OUT + 'repro-ovv-clientnav-late.png' })

await browser.close()
console.log('[repro] done')
