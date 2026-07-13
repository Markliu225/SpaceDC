import { test, expect } from '@playwright/test';

/**
 * Design gallery — switch the whole satellite design from the Twin page.
 * Preconditions (must be running):
 *   - backend @ :8001  (regenerates the USD + broadcasts on apply)
 *   - Vite dev @ :5173
 * Kit is NOT required: the switch is verified via backend state + UI echo.
 */
test.describe('design gallery', () => {
  test('lists presets with thumbnails and stats', async ({ page }) => {
    await page.goto('http://localhost:5173/satellite', { waitUntil: 'domcontentloaded' });

    // Trigger chip in the header strip.
    const trigger = page.getByRole('button', { name: /designs/i });
    await expect(trigger).toBeVisible({ timeout: 10_000 });
    await trigger.click();

    const dialog = page.getByRole('dialog', { name: /satellite design library/i });
    await expect(dialog).toBeVisible();

    // All six preset cards render with name + stats.
    for (const name of ['Balanced LEO-DC', 'Redwire Serving Node', 'Compute Max',
                        'Eco Light', 'Thermal Guard', 'Wide Wing']) {
      await expect(dialog.getByText(name, { exact: true })).toBeVisible();
    }

    // Thumbnails come from the backend preview endpoint and actually load.
    const firstImg = dialog.locator('img').first();
    await expect(firstImg).toHaveAttribute('src', /\/designs\/.+\/preview\.png/);
    await expect
      .poll(async () => firstImg.evaluate((el: HTMLImageElement) => el.naturalWidth), {
        timeout: 15_000,
      })
      .toBeGreaterThan(0);

    // Escape closes.
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
  });

  test('applying a design switches model + physics + workload', async ({ page }) => {
    await page.goto('http://localhost:5173/satellite', { waitUntil: 'domcontentloaded' });

    // Reset to a known design first (idempotent even if a previous run
    // left another design active).
    const reset = await page.request.post('http://localhost:8001/designs/baseline/apply');
    expect(reset.ok()).toBeTruthy();

    const trigger = page.getByRole('button', { name: /designs/i });
    await expect(trigger).toBeVisible({ timeout: 10_000 });
    await expect(trigger).toContainText('Balanced LEO-DC', { timeout: 10_000 });

    const before = await (await page.request.get('http://localhost:8001/state')).json();

    await trigger.click();
    const dialog = page.getByRole('dialog', { name: /satellite design library/i });

    // Click the Thermal Guard card → POST /designs/thermal_guard/apply.
    await dialog.getByText('Thermal Guard', { exact: true }).click();

    // Modal closes on success; the trigger chip echoes the new active design
    // once the state_update round-trips.
    await expect(dialog).not.toBeVisible({ timeout: 30_000 });
    await expect(trigger).toContainText('Thermal Guard', { timeout: 15_000 });

    // Backend truth: design id, hardware config, geometry (version bumped →
    // Kit reload trigger), and the workload profile all switched together.
    const after = await (await page.request.get('http://localhost:8001/state')).json();
    expect(after.design_id).toBe('thermal_guard');
    expect(after.workload_profile).toBe('burst');
    expect(after.satellite_config.gpu).toBe('H200');
    expect(after.satellite_config.radiator_material).toBe('OSR');
    expect(after.twin_geometry.solar_clusters_per_side).toBe(3);
    expect(after.twin_geometry.radiator_long).toBeCloseTo(3.0);
    expect(after.twin_geometry.version).toBeGreaterThan(before.twin_geometry.version);

    // Physics inputs follow the new design on the next ticks (areas are
    // recomputed every tick from the applied geometry).
    await expect
      .poll(async () => {
        const s = await (await page.request.get('http://localhost:8001/state')).json();
        return s.satellite.radiator_area_m2;
      }, { timeout: 10_000 })
      .toBeCloseTo(4 * (3.0 * 1.8) * ((3.0 / 1.5) * 1.8), 1);

    // Restore baseline so the suite leaves the demo in its default state.
    await page.request.post('http://localhost:8001/designs/baseline/apply');
  });
});
