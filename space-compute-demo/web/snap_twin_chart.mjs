import { chromium } from 'playwright'

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.goto('http://localhost:5174/satellite', { waitUntil: 'domcontentloaded' })
// Wait long enough for >30 samples of WS state_update to fill the buffer
// so the time series actually shows the sinusoidal motion the backend emits.
await page.waitForTimeout(40000)
await page.screenshot({ path: 'C:/Users/markl/AppData/Local/Temp/twin-chart-only.png' })
console.log('saved')
await browser.close()
