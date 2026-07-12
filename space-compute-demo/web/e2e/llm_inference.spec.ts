import { test, expect } from '@playwright/test';

/** Analytical LLM engine — flying the 'inference' schedule must resolve the
 *  active block through llm_perf's operating-point solve (engine=analytic):
 *  the backend reports phase/batch, DVFS frequency, realized draw and die
 *  temperature, the payload power equals draw × cards, and the Workload
 *  panel shows the operating-point strip. */
// Restore the default demo state even when an assertion throws — later
// serial specs share this backend.
test.afterEach(async ({ request }) => {
  await request.post('http://localhost:8001/designs/baseline/apply');
});

test('LLM inference flies the analytic operating point end to end', async ({ page }) => {
  test.setTimeout(120_000);

  await page.request.post('http://localhost:8001/designs/baseline/apply');
  await page.request.post('http://localhost:8001/workload_profile', {
    data: { profile: 'inference' },
  });
  await page.goto('http://localhost:5173/satellite', { waitUntil: 'domcontentloaded' });

  // Backend truth: an analytic decode operating point on /state.
  await expect
    .poll(async () => (await (await page.request.get('http://localhost:8001/state')).json())
      .satellite.workload_detail?.engine, { timeout: 20_000 })
    .toBe('analytic');
  const s = await (await page.request.get('http://localhost:8001/state')).json();
  const sat = s.satellite;
  const wd = sat.workload_detail;
  expect(wd.exec_phase).toBe('decode');
  expect(wd.batch).toBeGreaterThan(0);
  expect(wd.throughput_unit).toBe('tok/s');
  expect(wd.throughput_per_gpu).toBeGreaterThan(0);
  // DVFS governor settled somewhere real, cap is the EPS budget, and the
  // realized decode draw never exceeds it.
  expect(wd.freq_frac).toBeGreaterThan(0);
  expect(wd.freq_frac).toBeLessThanOrEqual(1);
  expect(wd.power_cap_w).toBeGreaterThan(0);
  expect(wd.power_w_per_gpu).toBeLessThanOrEqual(wd.power_cap_w + 0.1);
  // Physics runs on the model's realized draw.
  expect(Math.abs(sat.payload_power_w - wd.power_w_per_gpu * wd.gpu_count))
    .toBeLessThan(1.0);
  // Die = structure + draw·R_th, so it must sit above the structure temp.
  expect(wd.gpu_die_temp_c).toBeGreaterThan(sat.temperature_c);

  // UI: the operating-point strip renders phase, SM clock and die temp.
  const strip = page.getByTestId('llm-operating-point');
  await expect(strip).toBeVisible({ timeout: 15_000 });
  await expect(strip).toContainText('decode');
  await expect(strip).toContainText('SM');
  await expect(strip).toContainText('die');
});
