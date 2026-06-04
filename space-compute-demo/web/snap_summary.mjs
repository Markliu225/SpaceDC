import { chromium } from 'playwright'
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.goto('http://localhost:5174/satellite', { waitUntil: 'domcontentloaded' })
for (let i = 0; i < 90; i++) {
  if (/streaming/i.test(await page.evaluate(() => document.body.innerText))) break
  await new Promise(r => setTimeout(r, 1000))
}
await page.waitForTimeout(8000)
// Scroll the Configurator card all the way down so the Design Summary is in view.
await page.evaluate(() => {
  const card = document.querySelector('.overflow-y-auto')
  if (card) card.scrollTop = 10000
})
await page.waitForTimeout(400)
await page.screenshot({ path: 'C:/Users/markl/AppData/Local/Temp/twin-configurator-summary.png',
  clip: { x: 944, y: 70, width: 480, height: 600 } })
await browser.close()
console.log('done')
