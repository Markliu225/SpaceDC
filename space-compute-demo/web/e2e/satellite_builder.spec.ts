import { test, expect } from '@playwright/test';

const BACK  = 'http://localhost:8001';
const FRONT = 'http://localhost:5173';

/**
 * Satellite builder — the Twin page's build flow: pick a vendor platform,
 * design the structure, fit a GPU into each payload slot, choose the job
 * schedule, Run.
 *
 * The contract under test is that NOTHING reaches the live satellite until
 * Run, and that Run then applies all four steps atomically: hull, hardware
 * loadout, per-slot payload and workload profile.
 */
test.describe('satellite builder', () => {
  test('builds a platform slot by slot and commissions it', async ({ page }) => {
    test.setTimeout(180_000);

    // Known starting point — a design preset on the truss hull.
    await page.request.post(`${BACK}/designs/baseline/apply`);
    const before = await (await page.request.get(`${BACK}/state`)).json();

    await page.goto(`${FRONT}/satellite`, { waitUntil: 'domcontentloaded' });

    // The builder owns the page on first entry, and the four platforms load.
    const builder = page.getByTestId('satellite-builder');
    await expect(builder).toBeVisible({ timeout: 20_000 });
    for (const id of ['spacex', 'redwire', 'sophia', 'ada']) {
      await expect(page.getByTestId(`build-asset-${id}`)).toBeVisible({ timeout: 20_000 });
    }

    // Step 1 — platform.
    await page.getByTestId('build-asset-redwire').click();

    // Step 2 — structure: a radiator nudge must move the summary's area.
    await page.getByTestId('build-next').click();
    await page.getByLabel('increase Panel span').click();
    await page.getByTestId('build-attitude-nadir').click();

    // Step 3 — payload: empty two bay slots, fit one with a different card.
    await page.getByTestId('build-step-payload').click();
    await page.getByTestId('build-brush-empty').click();
    await page.getByTestId('build-slot-5').click();
    await page.getByTestId('build-slot-6').click();
    await page.getByTestId('build-brush-B200').click();
    await page.getByTestId('build-slot-0').click();
    await expect(page.getByTestId('build-slot-grid')).toContainText('B200');

    // Nothing has touched the live satellite yet.
    const during = await (await page.request.get(`${BACK}/state`)).json();
    expect(during.twin_geometry.architecture).toBe(before.twin_geometry.architecture);
    expect(during.satellite_config.gpu_slots ?? []).toEqual(before.satellite_config.gpu_slots ?? []);

    // Step 4 — workload: the fit verdicts are computed for THIS draft.
    await page.getByTestId('build-step-workload').click();
    await expect(page.getByTestId('build-workload-inference')).toBeVisible({ timeout: 20_000 });
    await page.getByTestId('build-workload-inference').click();

    // Run — one atomic apply, then the twin proper comes back.
    await page.getByTestId('build-run').click();
    await expect(builder).toBeHidden({ timeout: 90_000 });

    const after = await (await page.request.get(`${BACK}/state`)).json();
    expect(after.asset_id).toBe('redwire');
    expect(after.twin_geometry.architecture).toBe('redwire');
    expect(after.workload_profile).toBe('inference');
    expect(after.satellite.attitude_mode).toBe('nadir');
    // Seven-slot bay: slot 0 is a B200, slots 5-6 are empty, rest H200.
    expect(after.satellite_config.gpu_slots).toEqual(
      ['B200', 'H200', 'H200', 'H200', 'H200', null, null]);
    expect(after.satellite.gpu_count).toBe(5);
    // Primary GPU echoes the largest group, so the legacy dropdown/panels
    // keep describing the bay honestly.
    expect(after.satellite_config.gpu).toBe('H200');
    // A built satellite is a custom design, on a catalogued platform.
    expect(after.design_id).toBe('custom');

    // The Configurator's bay strip reports the mix the builder produced.
    await expect(page.getByTestId('bay-loadout')).toContainText('4×H200');
    await expect(page.getByTestId('bay-loadout')).toContainText('1×B200');

    // The chip reopens the builder.
    await page.getByTestId('open-builder').click();
    await expect(builder).toBeVisible({ timeout: 10_000 });
  });

  test('an empty bay cannot be commissioned', async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto(`${FRONT}/satellite`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('build-asset-spacex')).toBeVisible({ timeout: 20_000 });
    await page.getByTestId('build-asset-spacex').click();

    await page.getByTestId('build-step-payload').click();
    await page.getByTestId('build-brush-empty').click();
    await page.getByText('Clear', { exact: true }).click();

    // Next is refused while the bay holds no cards — a satellite with no
    // payload is not a design, and the backend rejects it too.
    await expect(page.getByTestId('build-next')).toBeDisabled();
    const r = await page.request.post(`${BACK}/satellite_build`, {
      data: { asset: 'spacex', config: {}, geometry: {},
              gpu_slots: new Array(12).fill(null), workload_profile: 'inference' },
    });
    expect(r.status()).toBe(422);
  });
});
