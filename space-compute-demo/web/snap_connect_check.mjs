import { chromium } from 'playwright'
const OUT = 'C:/Users/markl/AppData/Local/Temp/'
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.on('console', m => { const t = m.text(); if (/stream|webrtc|fallback|connect/i.test(t)) console.log('[page]', t) })
await page.goto('http://localhost:5174/mission', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(25000)
await page.screenshot({ path: OUT + 'connect-check.png' })
console.log('[snap] connect-check done')
await browser.close()
