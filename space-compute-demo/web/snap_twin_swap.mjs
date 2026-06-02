import { chromium } from 'playwright'
const OUT = 'C:/Users/markl/AppData/Local/Temp/'
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

async function waitStream(tag) {
  for (let i = 0; i < 90; i++) {
    if (/streaming/i.test(await page.evaluate(() => document.body.innerText))) {
      console.log(tag, 'streaming'); return true
    }
    await new Promise(r => setTimeout(r, 1000))
  }
  console.log(tag, 'NO-stream'); return false
}

// Twin page — new satellite model.
await page.goto('http://localhost:5174/satellite', { waitUntil: 'domcontentloaded' })
await waitStream('[twin]')
await page.waitForTimeout(12000)
await page.screenshot({ path: OUT + 'twin-new-model.png' })
console.log('[snap] twin-new-model captured')

// Mission page — task satellites should still be Satellite_v022.
await page.getByRole('link', { name: 'Mission' }).click()
await page.waitForTimeout(15000)
await page.screenshot({ path: OUT + 'mission-after-swap.png' })
console.log('[snap] mission-after-swap captured')

await browser.close()
console.log('[snap] done')
