// Verify Feature 3: Deployables controls render + a solar "+" click drives a
// backend regenerate (geometry version bump + USD solar count change).
import { chromium } from 'playwright'

const OUT = 'C:/Users/markl/AppData/Local/Temp/'
const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'],
})
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()
page.on('pageerror', (e) => console.error('[pageerror]', e.message))

await page.goto('http://localhost:5174/satellite', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(6000)

// Screenshot the right-rail Configurator (Deployables section visible).
await page.screenshot({ path: `${OUT}geom-controls.png`, clip: { x: 1095, y: 70, width: 345, height: 760 } })
console.log('[snap] geom-controls.png saved')

// Click the "Solar / side" increase button.
const before = await (await fetch('http://localhost:8001/twin_geometry')).json()
console.log('[geom] before:', JSON.stringify(before))
await page.getByRole('button', { name: 'increase Solar / side' }).click()
await page.waitForTimeout(3500)   // backend writes params + reruns the generator
const after = await (await fetch('http://localhost:8001/twin_geometry')).json()
console.log('[geom] after :', JSON.stringify(after))

await browser.close()
console.log('[snap] done')
