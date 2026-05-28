import { chromium } from 'playwright'

const OUT = 'C:/Users/markl/AppData/Local/Temp/'
const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'],
})
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
// The WebRTC signalling socket to Kit (:49100) is expected to fail when
// Kit isn't running — that's not a page error for this UI check.
const ignore = (s) => /49100|WebSocket connection to 'ws:\/\/127\.0\.0\.1:49100/.test(s)
page.on('pageerror', (e) => { if (!ignore(e.message)) errors.push(`[pageerror] ${e.message}`) })
page.on('console', (m) => { if (m.type() === 'error' && !ignore(m.text())) errors.push(`[console] ${m.text()}`) })

await page.goto('http://localhost:5174/mission', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(5000)

const presence = await page.evaluate(() => ({
  hasMissionStatus: /Mission Status/i.test(document.body.innerText),
  hasPhaseRail:     /AOI Acquired|Inferencing|Downlinking/i.test(document.body.innerText),
  hasLatency:       /Time to Result|天数地算/i.test(document.body.innerText),
  hasCast:          /Compute Hub|Sensor|Ground/i.test(document.body.innerText),
  hasStart:         /Start Task/i.test(document.body.innerText),
}))
console.log('[snap] presence', JSON.stringify(presence))

// Click Start Task, let the mock run into the compute phase, screenshot.
await page.getByRole('button', { name: /Start Task/i }).click()
await page.waitForTimeout(11000)   // acquire(2)+capture(3)+route(4) -> into compute
await page.screenshot({ path: `${OUT}mission-mid.png` })
console.log('[snap] saved mission-mid.png')

await page.waitForTimeout(8000)    // -> delivered
await page.screenshot({ path: `${OUT}mission-done.png` })
console.log('[snap] saved mission-done.png')

if (errors.length) { console.log('[snap] ERRORS:'); errors.forEach((e) => console.log('  ', e)) }
await browser.close()
process.exit(errors.length ? 1 : 0)
