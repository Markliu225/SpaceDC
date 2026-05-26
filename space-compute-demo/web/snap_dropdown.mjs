import { chromium } from 'playwright'
const browser = await chromium.launch({ headless: true, args: ['--use-gl=swiftshader'] })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()
await page.goto('http://localhost:5174/', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(6000)
// Click the constellation selector button (chevron-down trigger inside the first KPI tile).
const sel = page.locator('button[aria-haspopup="listbox"]').first()
await sel.click()
await page.waitForTimeout(700)
await page.screenshot({ path: 'C:/Users/markl/AppData/Local/Temp/dropdown.png', fullPage: false })
console.log('snapped')
await browser.close()
