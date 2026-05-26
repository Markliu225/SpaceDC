import { chromium } from 'playwright'

const URL = process.env.SNAP_URL ?? 'http://localhost:5174/satellite'
const OUT = process.env.SNAP_OUT ?? 'C:/Users/markl/AppData/Local/Temp/twin-page.png'

const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'],
})
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1.5,
})
const page = await ctx.newPage()

const consoleErrors = []
page.on('pageerror', (err) => { consoleErrors.push(`[pageerror] ${err.message}`) })
page.on('console',  (msg) => {
  if (msg.type() === 'error') consoleErrors.push(`[console.error] ${msg.text()}`)
})

console.log(`[snap] nav to ${URL}`)
await page.goto(URL, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(5000)

// Quick DOM presence check — bail if expected nodes aren't there.
const presence = await page.evaluate(() => {
  return {
    hasConfigurator: !!document.body.innerText.match(/Hardware Configurator/i),
    hasTimeSeries:   !!document.body.innerText.match(/Live Telemetry/i),
    hasSubsystems:   !!document.body.innerText.match(/Nominal|Warn|Fault/i),
    hasViewMode:     !!document.body.innerText.match(/Structure/i),
    hasSatPicker:    !!document.querySelector('[aria-haspopup="listbox"]'),
    bodyText:        document.body.innerText.slice(0, 800),
  }
})
console.log('[snap] presence', JSON.stringify(presence, null, 2))

if (consoleErrors.length > 0) {
  console.log('[snap] console errors:')
  for (const e of consoleErrors) console.log('  ', e)
}

await page.screenshot({ path: OUT, fullPage: false })
console.log(`[snap] saved ${OUT}`)

// Test a dropdown change end-to-end — find a "GPU" trigger button and click.
const gpuBtn = page.locator('button[aria-haspopup="listbox"]').nth(1) // sat picker is first
try {
  await gpuBtn.click({ timeout: 2000 })
  await page.waitForTimeout(400)
  // Click "Blackwell B200" if visible.
  const opt = page.getByText(/Blackwell B200/).first()
  if (await opt.count() > 0) {
    await opt.click()
    await page.waitForTimeout(800)
    await page.screenshot({ path: OUT.replace('.png', '-after-gpu.png'), fullPage: false })
    console.log('[snap] saved after-gpu snapshot')
  } else {
    console.log('[snap] GPU options not found in dropdown')
  }
} catch (e) {
  console.log('[snap] GPU dropdown interaction skipped:', e.message)
}

await browser.close()
console.log('[snap] done')
process.exit(consoleErrors.length > 0 ? 1 : 0)
