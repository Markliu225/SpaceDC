import { test, expect } from '@playwright/test';
import { dismissBuilder } from './twin';

/** Workload selector — switching the job schedule from the Twin page must
 *  swap the physics demand side, mark the design custom, restart the output
 *  counters, and the panel must show the live typed-job readout. */
test('workload panel switches schedules and shows live output', async ({ page }) => {
  test.setTimeout(120_000);

  // Known starting point.
  await page.request.post('http://localhost:8001/designs/baseline/apply');
  await page.goto('http://localhost:5173/satellite', { waitUntil: 'domcontentloaded' });
  await dismissBuilder(page);
  await page.waitForTimeout(4_000);

  // The Workload section renders with the live readout.
  const panel = page.locator('text=Job schedule').locator('..').locator('..');
  await expect(page.getByText('Design fit')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText('Running', { exact: true })).toBeVisible();

  // Open the schedule dropdown (baseline flies the multi-tier chat serving
  // schedule) and pick Burst response.
  await page.getByText('Chat serving (multi-tier)', { exact: true }).first().click();
  await page.getByText('Burst response', { exact: true }).click();

  // Backend truth: profile switched, design degraded to custom, demand-side
  // design check now reflects the burst schedule.
  await expect
    .poll(async () => (await (await page.request.get('http://localhost:8001/state')).json())
      .workload_profile, { timeout: 10_000 })
    .toBe('burst');
  const s = await (await page.request.get('http://localhost:8001/state')).json();
  expect(s.design_id).toBe('custom');
  // The design-check demand recomputes on the next 1 Hz physics tick.
  await expect
    .poll(async () => (await (await page.request.get('http://localhost:8001/state')).json())
      .satellite.solar_demand_avg_w, { timeout: 10_000 })
    .toBeLessThan(3200); // burst avg ~2.8 kW

  // Output counters restarted and accumulate under the new schedule.
  await page.waitForTimeout(4_000);
  const t = (await (await page.request.get('http://localhost:8001/state')).json())
    .satellite.workload_totals;
  expect(t.duration_s).toBeGreaterThan(1);
  expect(t.duration_s).toBeLessThan(60);
  expect(t.payload_kwh).toBeGreaterThan(0);

  // UI reflects the new schedule.
  await expect(panel.getByText('Burst response', { exact: true })).toBeVisible();

  // Restore the default demo state.
  await page.request.post('http://localhost:8001/designs/baseline/apply');
});
