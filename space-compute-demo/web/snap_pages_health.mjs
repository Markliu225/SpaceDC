import { chromium } from 'playwright'
const OUT = 'C:/Users/markl/AppData/Local/Temp/'
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

async function waitStream(tag) {
  for (let i = 0; i < 60; i++) {
    if (/streaming/i.test(await page.evaluate(() => document.body.innerText))) { console.log(tag, 'streaming'); return }
    await new Promise(r => setTimeout(r, 1000))
  }
  console.log(tag, 'NO-stream')
}

// Start on overview, let the stream come up once.
await page.goto('http://localhost:5174/', { waitUntil: 'domcontentloaded' })
await waitStream('[overview]')
await page.waitForTimeout(4000)
await page.screenshot({ path: OUT + 'health-overview.png' })

for (const [name, label] of [['satellite','Satellite Twin'], ['task','Task'], ['control','Control']]) {
  await page.getByRole('link', { name: label }).click().catch(async () => {
    await page.getByText(label, { exact: true }).first().click()
  })
  await page.waitForTimeout(7000)
  await page.screenshot({ path: OUT + `health-${name}.png` })
  console.log('[health]', name, 'captured')
}

// Back to overview to confirm it still renders Earth.
await page.getByRole('link', { name: 'Overview' }).click()
await page.waitForTimeout(7000)
await page.screenshot({ path: OUT + 'health-overview-return.png' })
console.log('[health] overview-return captured')

await browser.close()
console.log('[health] done')
