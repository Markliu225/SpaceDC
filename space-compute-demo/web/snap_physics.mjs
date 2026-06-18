// Verify Feature 4: the solar/radiator panels show LIVE geometry-driven physics
// and update when the deployable geometry changes.
import { chromium } from 'playwright'

const OUT = 'C:/Users/markl/AppData/Local/Temp/'
const BK = 'http://localhost:8001'
const SOLAR = '/World/Satellite/SolarArray/WingPosY/Cluster0_00/tripo_node/tripo_mesh'
const RAD   = '/World/Satellite/RadiatorArray/RadiatorTop/tripo_node/tripo_mesh'
const setGeom = (b) => fetch(`${BK}/twin_geometry`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })

const browser = await chromium.launch({ headless: true, args: ['--use-gl=swiftshader', '--ignore-gpu-blocklist'] })
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
page.on('pageerror', (e) => console.error('[pageerror]', e.message))

await setGeom({ solar_clusters_per_side: 2, radiator_long: 1.55, radiator_ratio: 2.5 })
await page.goto('http://localhost:5174/satellite', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(7000)

const clip = { x: 980, y: 90, width: 250, height: 300 }
const sel = (p) => page.evaluate((x) => window.__demoStore.setState({ selectedPrim: x }), p)

await sel(SOLAR); await page.waitForTimeout(800)
await page.screenshot({ path: `${OUT}phys-solar-2.png`, clip })
console.log('[snap] solar @2 clusters')

await setGeom({ solar_clusters_per_side: 4 }); await page.waitForTimeout(3000)
await sel(SOLAR); await page.waitForTimeout(500)
await page.screenshot({ path: `${OUT}phys-solar-4.png`, clip })
console.log('[snap] solar @4 clusters')

await setGeom({ radiator_long: 2.8, radiator_ratio: 2.0 }); await page.waitForTimeout(3000)
await sel(RAD); await page.waitForTimeout(500)
await page.screenshot({ path: `${OUT}phys-radiator.png`, clip })
console.log('[snap] radiator @big')

await setGeom({ solar_clusters_per_side: 2, radiator_long: 1.55, radiator_ratio: 2.5 })
await browser.close()
console.log('[snap] done')
