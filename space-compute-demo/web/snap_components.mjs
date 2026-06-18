// Verify component-level click-to-panel: drive selectedPrim for each component
// kind via the dev store hook and screenshot the resulting popup (top-right).
import { chromium } from 'playwright'

const OUT = 'C:/Users/markl/AppData/Local/Temp/'
const CASES = [
  ['server',    '/World/Satellite/Servers/Server_UpY_0/Chassis'],
  ['solar',     '/World/Satellite/SolarArray/WingPosY/Cluster0_00/tripo_node_a4f32a50/tripo_mesh_a4f32a50'],
  ['radiator',  '/World/Satellite/RadiatorArray/RadiatorTop/tripo_node_592ee2f8/tripo_mesh_592ee2f8'],
  ['structure', '/World/Satellite/Backbone/ParentNode/tripo_part_0/Mesh_8'],
  ['spine',     '/World/Satellite/Backbone/ParentNode/tripo_part_1/Mesh_9'],
]

const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'],
})
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()
page.on('pageerror', (e) => console.error('[pageerror]', e.message))

await page.goto('http://localhost:5174/satellite', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(6000)
const hasHook = await page.evaluate(() => !!window.__demoStore)
console.log('[check] __demoStore hook present:', hasHook)

for (const [name, prim] of CASES) {
  await page.evaluate((p) => window.__demoStore.setState({ selectedPrim: p }), prim)
  await page.waitForTimeout(700)
  // crop to the top-right popup region of the viewport
  await page.screenshot({ path: `${OUT}comp-${name}.png`, clip: { x: 980, y: 90, width: 380, height: 320 } })
  const matched = await page.evaluate(() => !!document.querySelector('.shadow-card'))
  console.log(`[snap] ${name}: prim set, popup-present=${matched} → comp-${name}.png`)
}
await browser.close()
console.log('[snap] done')
