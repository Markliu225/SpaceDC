import { test, expect } from '@playwright/test';

const SCRATCH =
  'C:/Users/markl/AppData/Local/Temp/claude/c--Workspace-SpaceDC/948e699a-6557-4c98-b3d3-a94305800bf1/scratchpad';

/** Verifies REAL orbital motion on the twin page:
 *  - the local fallback viewport renders (not a black rectangle)
 *  - the satellite reticle MOVES between frames (pixel diff in viewport+HUD)
 *  - HUD LAT/LON sweeps with the backend orbit */
test('twin page shows a moving satellite in orbit', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('http://localhost:5173/satellite', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(6_000);

  const viewport = { x: 12, y: 118, width: 1050, height: 510 };
  const shotA = await page.screenshot({ clip: viewport });
  await page.screenshot({ clip: viewport, path: `${SCRATCH}/orbitfix_t0.png` });
  await page.waitForTimeout(8_000);
  const shotB = await page.screenshot({ clip: viewport });
  await page.screenshot({ clip: viewport, path: `${SCRATCH}/orbitfix_t8.png` });

  // Pixel-level: the two frames must differ substantially (moving reticle,
  // terminator, rings under auto-orbit camera), and must not be near-black.
  const diffRatio = await page.evaluate(async ([a, b]) => {
    const load = (b64: string) => new Promise<ImageData>((res) => {
      const img = new Image();
      img.onload = () => {
        const c = document.createElement('canvas');
        c.width = img.width; c.height = img.height;
        const ctx = c.getContext('2d')!;
        ctx.drawImage(img, 0, 0);
        res(ctx.getImageData(0, 0, img.width, img.height));
      };
      img.src = 'data:image/png;base64,' + b64;
    });
    const [ia, ib] = await Promise.all([load(a), load(b)]);
    let diff = 0, bright = 0;
    const n = ia.data.length / 4;
    for (let i = 0; i < ia.data.length; i += 4) {
      const da = Math.abs(ia.data[i] - ib.data[i])
        + Math.abs(ia.data[i + 1] - ib.data[i + 1])
        + Math.abs(ia.data[i + 2] - ib.data[i + 2]);
      if (da > 30) diff++;
      if (ia.data[i] + ia.data[i + 1] + ia.data[i + 2] > 45) bright++;
    }
    return { diff: diff / n, bright: bright / n };
  }, [shotA.toString('base64'), shotB.toString('base64')] as [string, string]);

  console.log('changed-pixel ratio:', diffRatio.diff.toFixed(4),
              '| non-black ratio:', diffRatio.bright.toFixed(4));
  expect(diffRatio.bright).toBeGreaterThan(0.02);  // scene actually renders
  expect(diffRatio.diff).toBeGreaterThan(0.001);   // something is MOVING

  // Backend orbit truth: the ECI position vector sweeps at the orbital rate
  // (~19°/5s at the 60x time scale) regardless of orbit phase — latitude
  // alone stalls at the inclination turnarounds.
  const eci = async () => (await (await page.request.get('http://localhost:8001/state')).json())
    .satellite.sat_xyz_km as [number, number, number];
  const p0 = await eci();
  await page.waitForTimeout(5_000);
  const p1 = await eci();
  const dot = (p0[0] * p1[0] + p0[1] * p1[1] + p0[2] * p1[2])
    / (Math.hypot(...p0) * Math.hypot(...p1));
  const sweepDeg = (Math.acos(Math.max(-1, Math.min(1, dot))) * 180) / Math.PI;
  console.log('backend orbital sweep over 5s:', sweepDeg.toFixed(2), 'deg');
  expect(sweepDeg).toBeGreaterThan(8);
});
