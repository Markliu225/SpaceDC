# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: orbit_and_nav.spec.ts >> orbit motion + page-triggered camera switch
- Location: e2e\orbit_and_nav.spec.ts:8:1

# Error details

```
Test timeout of 60000ms exceeded.
```

```
Error: page.waitForFunction: Test timeout of 60000ms exceeded.
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
      - generic [ref=e13]: T+000:02:28
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
              - generic [ref=e303]: "-25.8 / -94.7°"
            - generic [ref=e304]:
              - generic [ref=e305]: Altitude
              - generic [ref=e306]: "422"
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
              - generic [ref=e318]: 1,048
              - generic [ref=e319]: W
            - generic [ref=e320]:
              - generic [ref=e321]: Task
              - generic [ref=e322]: packaging
          - generic [ref=e323]:
            - generic [ref=e325]:
              - generic [ref=e326]: GPU Util
              - generic [ref=e327]:
                - generic [ref=e328]: "37"
                - generic [ref=e329]: "%"
            - generic [ref=e333]:
              - generic [ref=e334]: Battery
              - generic [ref=e335]:
                - generic [ref=e336]: "77"
                - generic [ref=e337]: "%"
            - generic [ref=e341]:
              - generic [ref=e342]: Temp
              - generic [ref=e343]:
                - generic [ref=e344]: "62.6"
                - generic [ref=e345]: °C
      - generic [ref=e349]:
        - generic [ref=e350]:
          - generic [ref=e351]: Event Log
          - button "All Events" [ref=e353] [cursor=pointer]:
            - text: All Events
            - img [ref=e354]
        - generic [ref=e356]:
          - generic [ref=e357]:
            - generic [ref=e358]: 09:50:08
            - generic [ref=e360]: Eclipse exit
            - generic [ref=e361]: SAT-12
          - generic [ref=e362]:
            - generic [ref=e363]: 09:49:56
            - generic [ref=e365]: Eclipse exit
            - generic [ref=e366]: SAT-12
          - generic [ref=e367]:
            - generic [ref=e368]: 09:49:44
            - generic [ref=e370]: Link established
            - generic [ref=e371]: SAT-07 → SAT-13
          - generic [ref=e372]:
            - generic [ref=e373]: 09:49:32
            - generic [ref=e375]: Link established
            - generic [ref=e376]: SAT-07 → SAT-13
          - generic [ref=e377]:
            - generic [ref=e378]: 09:49:20
            - generic [ref=e380]: GPU thermal alarm
            - generic [ref=e381]: SAT-09 · 78°C
          - generic [ref=e382]:
            - generic [ref=e383]: 14:21:04
            - generic [ref=e385]: Link established
            - generic [ref=e386]: SAT-07 → SAT-13
          - generic [ref=e387]:
            - generic [ref=e388]: 14:20:51
            - generic [ref=e390]: Task created
            - generic [ref=e391]: SAT-07 · maritime
          - generic [ref=e392]:
            - generic [ref=e393]: 14:19:33
            - generic [ref=e395]: Thermal warning cleared
            - generic [ref=e396]: SAT-04
          - generic [ref=e397]:
            - generic [ref=e398]: 14:18:17
            - generic [ref=e400]: AOS Reykjavik
            - generic [ref=e401]: GS-EU-01 · SAT-15
          - generic [ref=e402]:
            - generic [ref=e403]: 14:16:02
            - generic [ref=e405]: Downlink complete
            - generic [ref=e406]: SAT-09 · 412 MB
          - generic [ref=e407]:
            - generic [ref=e408]: 14:14:48
            - generic [ref=e410]: Comms drop (recovered)
            - generic [ref=e411]: SAT-22
          - generic [ref=e412]:
            - generic [ref=e413]: 14:12:31
            - generic [ref=e415]: Battery charge resumed
            - generic [ref=e416]: SAT-13
          - generic [ref=e417]:
            - generic [ref=e418]: 14:10:09
            - generic [ref=e420]: Constellation sync
            - generic [ref=e421]: ALL · 22 nodes
      - generic [ref=e423]:
        - generic [ref=e424]:
          - generic [ref=e425]: Cost Profile
          - generic [ref=e426]: ISS (single satellite) · 1 satellites
        - generic [ref=e427]:
          - generic [ref=e428]:
            - img [ref=e429]
            - generic [ref=e432]:
              - generic [ref=e433]: Capital Expenditure
              - generic [ref=e434]:
                - generic [ref=e435]: "60"
                - generic [ref=e436]: million USD
              - generic [ref=e437]: 60.0 million per satellite
          - generic [ref=e438]:
            - img [ref=e439]
            - generic [ref=e441]:
              - generic [ref=e442]: Operating Expense
              - generic [ref=e443]:
                - generic [ref=e444]: "14"
                - generic [ref=e445]: million USD / year
          - generic [ref=e446]:
            - img [ref=e447]
            - generic [ref=e452]:
              - generic [ref=e453]: Launch Cost
              - generic [ref=e454]:
                - generic [ref=e455]: "22"
                - generic [ref=e456]: million USD
              - generic [ref=e457]: 1 tonnes payload
          - generic [ref=e458]:
            - img [ref=e459]
            - generic [ref=e462]:
              - generic [ref=e463]: Lifetime Total
              - generic [ref=e464]:
                - generic [ref=e465]: "172"
                - generic [ref=e466]: million USD
              - generic [ref=e467]: 8 year design life
          - generic [ref=e468]:
            - img [ref=e469]
            - generic [ref=e472]:
              - generic [ref=e473]: Compute Capacity
              - generic [ref=e474]:
                - generic [ref=e475]: "1"
                - generic [ref=e476]: petaFLOPS
              - generic [ref=e477]: 66666.7 thousand USD per petaFLOP
          - generic [ref=e478]:
            - img [ref=e479]
            - generic [ref=e481]:
              - generic [ref=e482]: Power Draw
              - generic [ref=e483]:
                - generic [ref=e484]: "4"
                - generic [ref=e485]: kilowatts
          - generic [ref=e486]:
            - img [ref=e487]
            - generic [ref=e491]:
              - generic [ref=e492]: Cost Per Satellite
              - generic [ref=e493]:
                - generic [ref=e494]: "60.0"
                - generic [ref=e495]: million USD
          - generic [ref=e496]:
            - img [ref=e497]
            - generic [ref=e500]:
              - generic [ref=e501]: Payback Period
              - generic [ref=e502]:
                - generic [ref=e503]: "12.0"
                - generic [ref=e504]: years
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | import { mkdirSync } from 'node:fs';
  3  | import { dirname, resolve } from 'node:path';
  4  | import { fileURLToPath } from 'node:url';
  5  | 
  6  | const __dirname = dirname(fileURLToPath(import.meta.url));
  7  | 
  8  | test('orbit motion + page-triggered camera switch', async ({ page }) => {
  9  |   await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' });
  10 |   await expect(page.locator('.dot.dot--ok')).toBeVisible({ timeout: 10_000 });
> 11 |   await page.waitForFunction(() => {
     |              ^ Error: page.waitForFunction: Test timeout of 60000ms exceeded.
  12 |     const v = document.getElementById('remote-video') as HTMLVideoElement | null;
  13 |     return !!v && v.videoWidth > 0;
  14 |   }, { timeout: 30_000 });
  15 | 
  16 |   // Give Kit a moment to consume its first state poll.
  17 |   await page.waitForTimeout(2500);
  18 |   const out = resolve(__dirname, '../test-results');
  19 |   mkdirSync(out, { recursive: true });
  20 | 
  21 |   // Capture overview
  22 |   await page.screenshot({ path: resolve(out, 'scene_overview.png') });
  23 | 
  24 |   // Show orbit motion: wait 5 s, snap again — satellite position should differ.
  25 |   await page.waitForTimeout(5000);
  26 |   await page.screenshot({ path: resolve(out, 'scene_overview_5s.png') });
  27 | 
  28 |   // Navigate to Satellite Twin — page mounts, changeCamera('satellite') fires.
  29 |   await page.getByRole('link', { name: 'Satellite Twin' }).click();
  30 |   // Wait for Kit to process preset change + re-frame.
  31 |   await page.waitForTimeout(4000);
  32 |   await page.screenshot({ path: resolve(out, 'scene_satellite.png') });
  33 | 
  34 |   // Back to Overview to verify switch-back.
  35 |   await page.getByRole('link', { name: 'Overview', exact: true }).click();
  36 |   await page.waitForTimeout(4000);
  37 |   await page.screenshot({ path: resolve(out, 'scene_overview_return.png') });
  38 | });
  39 | 
```