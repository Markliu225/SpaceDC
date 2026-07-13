# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: smoke.spec.ts >> full stack: web connects to backend + attempts Kit stream
- Location: e2e\smoke.spec.ts:10:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('.cards .card').first()
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for locator('.cards .card').first()

```

# Page snapshot

```yaml
- generic [ref=e3]:
  - banner [ref=e4]:
    - generic [ref=e5]: SPACE-COMPUTE-DEMO
    - navigation [ref=e6]:
      - link "Overview" [ref=e7] [cursor=pointer]:
        - /url: /
      - link "Satellite Twin" [ref=e8] [cursor=pointer]:
        - /url: /satellite
      - link "Mission" [ref=e9] [cursor=pointer]:
        - /url: /mission
      - link "Task" [ref=e10] [cursor=pointer]:
        - /url: /task
      - link "Control" [ref=e11] [cursor=pointer]:
        - /url: /control
    - generic [ref=e12]:
      - generic [ref=e13]: T+000:04:02
      - generic [ref=e15]: LIVE
      - button "Play" [ref=e16] [cursor=pointer]: ▶
      - button "Pause" [ref=e17] [cursor=pointer]: ❚❚
      - button "Reset" [ref=e18] [cursor=pointer]: ⟲
  - main [ref=e19]:
    - generic [ref=e20]:
      - generic [ref=e22]:
        - generic [ref=e23]:
          - generic [ref=e24]: Constellation
          - button "ISS (single satellite)" [ref=e26] [cursor=pointer]:
            - generic [ref=e27]: ISS (single satellite)
            - img [ref=e28]
          - generic [ref=e30]:
            - text: 1p · 1s · 51.6°
            - generic [ref=e31]: 417 km
        - generic [ref=e32]:
          - generic [ref=e33]: Total Satellites
          - generic [ref=e34]:
            - generic [ref=e35]:
              - generic [ref=e36]: "1"
              - generic [ref=e37]: ● 1 online
            - generic [ref=e38]: 0 eclipse · 0 standby · 0 offline
        - generic [ref=e39]:
          - generic [ref=e40]: Active Links
          - generic [ref=e41]:
            - generic [ref=e42]:
              - generic [ref=e43]: "1"
              - generic [ref=e44]: 0 ISL / 1 GSL
            - generic [ref=e45]: cross-link mesh
        - generic [ref=e46]:
          - generic [ref=e47]: Coverage
          - generic [ref=e48]:
            - generic [ref=e49]:
              - generic [ref=e50]: "9"
              - generic [ref=e51]: "%"
            - generic [ref=e52]: global land + sea
        - generic [ref=e53]:
          - generic [ref=e54]: Agg. Throughput
          - generic [ref=e55]:
            - generic [ref=e56]:
              - generic [ref=e57]: "60"
              - generic [ref=e58]: Mbps
            - generic [ref=e59]: downlink aggregate
      - generic [ref=e61]:
        - generic [ref=e63]:
          - generic:
            - generic: connecting to 127.0.0.1:49100…
        - generic [ref=e69]: Omniverse connecting…
        - img [ref=e70]:
          - generic [ref=e73]: "N"
      - generic [ref=e75]:
        - generic [ref=e76]:
          - generic [ref=e77]: Constellation Status
          - generic [ref=e78]: 51.6° · 1 sats
        - img [ref=e80]
        - generic [ref=e262]:
          - generic [ref=e265]: Online
          - generic [ref=e268]: Eclipse
          - generic [ref=e271]: Standby
          - generic [ref=e274]: Offline
      - generic [ref=e276]:
        - generic [ref=e277]:
          - generic [ref=e278]:
            - generic [ref=e279]: Selected Satellite
            - button "SAT-01" [ref=e281] [cursor=pointer]:
              - generic [ref=e282]: SAT-01
              - img [ref=e284]
          - generic [ref=e286]: ISS (single satellite) · plane 1/1
        - generic [ref=e287]:
          - generic [ref=e288]:
            - generic [ref=e289]:
              - generic [ref=e290]: Orbit
              - generic [ref=e291]: LEO
            - generic [ref=e292]:
              - generic [ref=e293]: GPU
              - generic [ref=e294]: H100
            - generic [ref=e295]:
              - generic [ref=e296]: Sunlit
              - generic [ref=e297]: "YES"
            - generic [ref=e298]:
              - generic [ref=e299]: GS Visible
              - generic [ref=e300]: "YES"
            - generic [ref=e301]:
              - generic [ref=e302]: Lat / Lon
              - generic [ref=e303]: "-28.9 / -115.0°"
            - generic [ref=e304]:
              - generic [ref=e305]: Altitude
              - generic [ref=e306]: "421"
              - generic [ref=e307]: km
            - generic [ref=e308]:
              - generic [ref=e309]: Solar In
              - generic [ref=e310]: 4,200
              - generic [ref=e311]: W
            - generic [ref=e312]:
              - generic [ref=e313]: Platform Pwr
              - generic [ref=e314]: "600"
              - generic [ref=e315]: W
            - generic [ref=e316]:
              - generic [ref=e317]: Payload Pwr
              - generic [ref=e318]: 1,761
              - generic [ref=e319]: W
            - generic [ref=e320]:
              - generic [ref=e321]: Task
              - generic [ref=e322]: capturing
          - generic [ref=e323]:
            - generic [ref=e325]:
              - generic [ref=e326]: GPU Util
              - generic [ref=e327]:
                - generic [ref=e328]: "79"
                - generic [ref=e329]: "%"
            - generic [ref=e333]:
              - generic [ref=e334]: Battery
              - generic [ref=e335]:
                - generic [ref=e336]: "76"
                - generic [ref=e337]: "%"
            - generic [ref=e341]:
              - generic [ref=e342]: Temp
              - generic [ref=e343]:
                - generic [ref=e344]: "70.2"
                - generic [ref=e345]: °C
      - generic [ref=e349]:
        - generic [ref=e350]:
          - generic [ref=e351]: Event Log
          - button "All Events" [ref=e353] [cursor=pointer]:
            - text: All Events
            - img [ref=e354]
        - generic [ref=e356]:
          - generic [ref=e357]:
            - generic [ref=e358]: 14:21:04
            - generic [ref=e360]: Link established
            - generic [ref=e361]: SAT-07 → SAT-13
          - generic [ref=e362]:
            - generic [ref=e363]: 14:20:51
            - generic [ref=e365]: Task created
            - generic [ref=e366]: SAT-07 · maritime
          - generic [ref=e367]:
            - generic [ref=e368]: 14:19:33
            - generic [ref=e370]: Thermal warning cleared
            - generic [ref=e371]: SAT-04
          - generic [ref=e372]:
            - generic [ref=e373]: 14:18:17
            - generic [ref=e375]: AOS Reykjavik
            - generic [ref=e376]: GS-EU-01 · SAT-15
          - generic [ref=e377]:
            - generic [ref=e378]: 14:16:02
            - generic [ref=e380]: Downlink complete
            - generic [ref=e381]: SAT-09 · 412 MB
          - generic [ref=e382]:
            - generic [ref=e383]: 14:14:48
            - generic [ref=e385]: Comms drop (recovered)
            - generic [ref=e386]: SAT-22
          - generic [ref=e387]:
            - generic [ref=e388]: 14:12:31
            - generic [ref=e390]: Battery charge resumed
            - generic [ref=e391]: SAT-13
          - generic [ref=e392]:
            - generic [ref=e393]: 14:10:09
            - generic [ref=e395]: Constellation sync
            - generic [ref=e396]: ALL · 22 nodes
      - generic [ref=e398]:
        - generic [ref=e399]:
          - generic [ref=e400]: Cost Profile
          - generic [ref=e401]: ISS (single satellite) · 1 satellites
        - generic [ref=e402]:
          - generic [ref=e403]:
            - img [ref=e404]
            - generic [ref=e407]:
              - generic [ref=e408]: Capital Expenditure
              - generic [ref=e409]:
                - generic [ref=e410]: "60"
                - generic [ref=e411]: million USD
              - generic [ref=e412]: 60.0 million per satellite
          - generic [ref=e413]:
            - img [ref=e414]
            - generic [ref=e416]:
              - generic [ref=e417]: Operating Expense
              - generic [ref=e418]:
                - generic [ref=e419]: "14"
                - generic [ref=e420]: million USD / year
          - generic [ref=e421]:
            - img [ref=e422]
            - generic [ref=e427]:
              - generic [ref=e428]: Launch Cost
              - generic [ref=e429]:
                - generic [ref=e430]: "22"
                - generic [ref=e431]: million USD
              - generic [ref=e432]: 1 tonnes payload
          - generic [ref=e433]:
            - img [ref=e434]
            - generic [ref=e437]:
              - generic [ref=e438]: Lifetime Total
              - generic [ref=e439]:
                - generic [ref=e440]: "172"
                - generic [ref=e441]: million USD
              - generic [ref=e442]: 8 year design life
          - generic [ref=e443]:
            - img [ref=e444]
            - generic [ref=e447]:
              - generic [ref=e448]: Compute Capacity
              - generic [ref=e449]:
                - generic [ref=e450]: "1"
                - generic [ref=e451]: petaFLOPS
              - generic [ref=e452]: 66666.7 thousand USD per petaFLOP
          - generic [ref=e453]:
            - img [ref=e454]
            - generic [ref=e456]:
              - generic [ref=e457]: Power Draw
              - generic [ref=e458]:
                - generic [ref=e459]: "4"
                - generic [ref=e460]: kilowatts
          - generic [ref=e461]:
            - img [ref=e462]
            - generic [ref=e466]:
              - generic [ref=e467]: Cost Per Satellite
              - generic [ref=e468]:
                - generic [ref=e469]: "60.0"
                - generic [ref=e470]: million USD
          - generic [ref=e471]:
            - img [ref=e472]
            - generic [ref=e475]:
              - generic [ref=e476]: Payback Period
              - generic [ref=e477]:
                - generic [ref=e478]: "12.0"
                - generic [ref=e479]: years
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | /**
  4  |  * End-to-end smoke test for Phase 1.
  5  |  * Preconditions (must be running):
  6  |  *   - backend @ :8001
  7  |  *   - Vite dev @ :5173
  8  |  *   - Kit streaming @ :49100
  9  |  */
  10 | test('full stack: web connects to backend + attempts Kit stream', async ({ page }) => {
  11 |   const logs: string[] = [];
  12 |   page.on('console', (msg) => logs.push(`[${msg.type()}] ${msg.text()}`));
  13 |   page.on('pageerror', (err) => logs.push(`[error] ${err.message}`));
  14 | 
  15 |   await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
  16 | 
  17 |   // Backend WS should connect and status dot should turn green within 5 s.
  18 |   await expect(page.locator('.dot.dot--ok')).toBeVisible({ timeout: 10_000 });
  19 | 
  20 |   // Sim time should advance (start with T+000:00:00, then change within 3 ticks).
  21 |   const firstTime = await page.locator('.shell__status span').first().innerText();
  22 |   await page.waitForTimeout(2500);
  23 |   const secondTime = await page.locator('.shell__status span').first().innerText();
  24 |   expect(secondTime).not.toBe(firstTime);
  25 | 
  26 |   // Status cards should populate.
> 27 |   await expect(page.locator('.cards .card').first()).toBeVisible();
     |                                                      ^ Error: expect(locator).toBeVisible() failed
  28 |   const cardCount = await page.locator('.cards .card').count();
  29 |   expect(cardCount).toBeGreaterThanOrEqual(10);
  30 | 
  31 |   // SceneEmbed should mount — either the video container (stream ready) or placeholder.
  32 |   await expect(page.locator('.scene-embed')).toBeVisible();
  33 | 
  34 |   // Wait up to 20 s for stream to start OR explicit failure. "timeout" means still connecting.
  35 |   const finalStatus = await Promise.race([
  36 |     page.waitForSelector('#main-div[style*="display: block"]', { timeout: 20_000 }).then(() => 'ready'),
  37 |     page.waitForFunction(
  38 |       () => (document.querySelector('.scene-embed__placeholder')?.textContent ?? '').toLowerCase().includes('failed'),
  39 |       { timeout: 20_000 },
  40 |     ).then(() => 'failed'),
  41 |   ]).catch(() => 'timeout');
  42 | 
  43 |   console.log('final scene status:', finalStatus);
  44 |   console.log('console log tail:\n' + logs.slice(-30).join('\n'));
  45 | 
  46 |   // We pass if the stream reached ready (best case) OR reached failed (Kit unreachable — backend+UI still verified).
  47 |   expect(['ready', 'failed']).toContain(finalStatus);
  48 | });
  49 | 
  50 | test('task page: Start Task flows through backend state machine', async ({ page }) => {
  51 |   await page.goto('http://localhost:5173/task', { waitUntil: 'domcontentloaded' });
  52 |   await expect(page.locator('.dot.dot--ok')).toBeVisible({ timeout: 10_000 });
  53 |   await page.getByRole('button', { name: 'Start Task' }).click();
  54 |   // Task card should go from "no task" to showing a task id.
  55 |   await expect(page.locator('.task-card')).toContainText(/task-\d+/, { timeout: 5_000 });
  56 | });
  57 | 
```