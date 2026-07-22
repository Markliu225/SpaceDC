import { test, expect } from '@playwright/test';

/**
 * Live what-if comparison — variant engines tick in lockstep with the live
 * 1 Hz physics tick and their curves overlay the Twin page telemetry strip.
 * Preconditions (must be running):
 *   - backend @ :8001
 *   - Vite dev @ :5173
 * Kit is NOT required.
 */
test.describe('live compare', () => {
  test('backend steps variants in lockstep and curves diverge over time', async ({ page }) => {
    // Known design state (WhitePaint radiators).
    const reset = await page.request.post('http://localhost:8001/designs/baseline/apply');
    expect(reset.ok()).toBeTruthy();

    const start = await page.request.post('http://localhost:8001/compare/start', {
      data: { dimension: 'radiator_material', values: ['Aluminum', 'OSR', 'Graphite'] },
    });
    expect(start.ok()).toBeTruthy();
    const started = await start.json();
    expect(started.compare_live.variants).toHaveLength(3);

    // All variants seed from the SAME instant → identical first sample.
    const s0 = (await (await page.request.get('http://localhost:8001/state')).json()).compare_live;
    expect(s0.active).toBe(true);
    const t0 = s0.variants.map((v: { temperature_c: number }) => v.temperature_c);
    expect(Math.abs(t0[0] - t0[1])).toBeLessThan(0.5);

    // Lockstep: elapsed_s grows with the live tick; curves diverge — the
    // bare-aluminium radiator (ε 0.10) runs hotter than OSR (ε 0.92).
    await expect
      .poll(async () => {
        const s = (await (await page.request.get('http://localhost:8001/state')).json()).compare_live;
        return s?.elapsed_s ?? 0;
      }, { timeout: 20_000 })
      .toBeGreaterThanOrEqual(6);

    const s1 = (await (await page.request.get('http://localhost:8001/state')).json()).compare_live;
    const tAl  = s1.variants[0].temperature_c;
    const tOsr = s1.variants[1].temperature_c;
    expect(tAl - tOsr).toBeGreaterThan(1.0);

    // Stop clears compare_live from the broadcast state.
    const stop = await page.request.post('http://localhost:8001/compare/stop');
    expect(stop.ok()).toBeTruthy();
    const after = (await (await page.request.get('http://localhost:8001/state')).json()).compare_live;
    expect(after).toBeNull();

    // Validation: unknown dimension / too few values → 422.
    const bad1 = await page.request.post('http://localhost:8001/compare/start', {
      data: { dimension: 'nope', values: ['a', 'b'] },
    });
    expect(bad1.status()).toBe(422);
    const bad2 = await page.request.post('http://localhost:8001/compare/start', {
      data: { dimension: 'gpu', values: ['H100'] },
    });
    expect(bad2.status()).toBe(422);
  });

  test('panel starts a live comparison and the strip overlays growing curves', async ({ page }) => {
    // Baseline flies WhitePaint radiators, so the OSR/Graphite chips below
    // are guaranteed unpicked (a chip click TOGGLES the seeded live pick).
    const reset = await page.request.post('http://localhost:8001/designs/baseline/apply');
    expect(reset.ok()).toBeTruthy();
    await page.request.post('http://localhost:8001/compare/stop');

    await page.goto('http://localhost:5173/satellite', { waitUntil: 'domcontentloaded' });

    await page.getByTestId('compare-open').click();
    const dialog = page.getByRole('dialog', { name: /what-if comparison/i });
    await expect(dialog).toBeVisible();

    // Radiator coating is the default dimension; live value (WhitePaint) is
    // pre-picked. Add two more coatings → 3 variants.
    await dialog.getByRole('button', { name: /OSR/ }).click();
    await dialog.getByRole('button', { name: /Graphite/ }).click();

    const runBtn = page.getByTestId('compare-run');
    await expect(runBtn).toBeEnabled();
    await runBtn.click();

    // Modal closes on success; the trigger chip shows the LIVE badge.
    await expect(dialog).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('compare-open')).toContainText('LIVE', { timeout: 10_000 });

    // The strip shows the what-if legend and, once ≥2 samples ticked in,
    // one dashed overlay per variant per mini-chart (3 × 5 = 15 paths).
    await expect(page.getByTestId('compare-legend')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('compare-overlay')).toHaveCount(15, { timeout: 15_000 });

    // Stop from the panel; overlays and legend disappear.
    await page.getByTestId('compare-open').click();
    await page.getByTestId('compare-stop').click();
    await expect(page.getByTestId('compare-legend')).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('compare-overlay')).toHaveCount(0, { timeout: 10_000 });
    await page.keyboard.press('Escape');
  });

  test('design dimension works while the live design is custom', async ({ page }) => {
    // Degrade the live design to "custom" (any manual config edit does) —
    // the panel must NOT seed an invisible un-deselectable 'custom' pick.
    const degrade = await page.request.post('http://localhost:8001/satellite_config', {
      data: { gpu: 'H100' },
    });
    expect(degrade.ok()).toBeTruthy();

    await page.goto('http://localhost:5173/satellite', { waitUntil: 'domcontentloaded' });
    await page.getByTestId('compare-open').click();
    const dialog = page.getByRole('dialog', { name: /what-if comparison/i });

    await dialog.getByRole('button', { name: /whole design/i }).click();
    // No phantom pick: start must stay disabled until TWO real designs picked.
    const runBtn = page.getByTestId('compare-run');
    await expect(runBtn).toBeDisabled();
    await dialog.getByRole('button', { name: 'Balanced LEO-DC' }).click();
    await dialog.getByRole('button', { name: 'Compute Max' }).click();
    await expect(runBtn).toBeEnabled();
    await runBtn.click();
    await expect(dialog).not.toBeVisible({ timeout: 10_000 });

    // Two design variants are ticking.
    await expect
      .poll(async () => {
        const s = (await (await page.request.get('http://localhost:8001/state')).json()).compare_live;
        return s?.variants?.length ?? 0;
      }, { timeout: 10_000 })
      .toBe(2);

    // Leave the demo in its default state.
    await page.request.post('http://localhost:8001/compare/stop');
    await page.request.post('http://localhost:8001/designs/baseline/apply');
  });
});
