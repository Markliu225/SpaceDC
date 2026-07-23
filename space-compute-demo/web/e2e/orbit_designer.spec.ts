import { test, expect } from '@playwright/test';

/**
 * Orbit designer + Singapore ground-station visibility (Overview page).
 * Preconditions (must be running):
 *   - backend @ :8001
 *   - Vite dev @ :5173
 * Kit is NOT required.
 */
test.describe('orbit designer', () => {
  test('designs a constellation from orbital elements and it goes live', async ({ page }) => {
    // Known starting constellation.
    const reset = await page.request.post('http://localhost:8001/constellation/single_iss');
    expect(reset.ok()).toBeTruthy();

    // The designer round-trips the six classical elements exactly.
    const apply = await page.request.post('http://localhost:8001/orbit_design', {
      data: { altitude_km: 550, eccentricity: 0.001, inclination_deg: 53,
              raan_deg: 20, arg_perigee_deg: 90, mean_anomaly_deg: 270,
              planes: 3, sats_per_plane: 8, phasing: 1 },
    });
    expect(apply.ok()).toBeTruthy();
    const body = await apply.json();
    expect(body.active).toBe('custom_design');
    expect(body.elements.inclination_deg).toBeCloseTo(53, 3);
    expect(body.elements.raan_deg).toBeCloseTo(20, 3);
    expect(body.elements.arg_perigee_deg).toBeCloseTo(90, 3);
    expect(body.elements.mean_anomaly_deg).toBeCloseTo(270, 3);
    expect(body.elements.eccentricity).toBeCloseTo(0.001, 5);
    expect(Math.abs(body.elements.altitude_km - 550)).toBeLessThan(5);
    expect(body.walker.total_sats).toBe(24);

    // The design is the ACTIVE constellation: state + ring detail follow.
    await expect
      .poll(async () => {
        const s = await (await page.request.get('http://localhost:8001/state')).json();
        return s.constellation?.constellation_id;
      }, { timeout: 10_000 })
      .toBe('custom_design');
    const detail = await (await page.request.get('http://localhost:8001/constellations/custom_design')).json();
    expect(detail.ring_eci_km.length).toBeGreaterThan(64);

    // UI: elements readout shows the designed values.
    await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' });
    const els = page.getByTestId('orbit-elements');
    await expect(els).toBeVisible({ timeout: 15_000 });
    await expect(els).toContainText('53.00°', { timeout: 10_000 });
    await expect(els).toContainText('20.00°');

    // Invalid designs are rejected.
    const bad = await page.request.post('http://localhost:8001/orbit_design', {
      data: { altitude_km: 50 },
    });
    expect(bad.status()).toBe(422);
  });

  test('marks Singapore and reports live + analyzed communication visibility', async ({ page }) => {
    await page.request.post('http://localhost:8001/ground_target', { data: { enabled: false } });
    await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' });

    // Toggle through the UI.
    const toggle = page.getByTestId('ground-target-toggle');
    await expect(toggle).toBeVisible({ timeout: 15_000 });
    await toggle.click();
    await expect(page.getByTestId('ground-visibility-live')).toBeVisible({ timeout: 10_000 });

    // Live visibility rides the broadcast state.
    await expect
      .poll(async () => {
        const s = await (await page.request.get('http://localhost:8001/state')).json();
        return s.ground_target?.enabled === true
          && typeof s.ground_target?.visible_sats === 'number';
      }, { timeout: 10_000 })
      .toBe(true);

    // Pass analysis over one orbit: sane invariants.
    await page.getByTestId('ground-analyze').click();
    await expect(page.getByTestId('ground-passes')).toBeVisible({ timeout: 30_000 });
    const vis = await (await page.request.get('http://localhost:8001/ground_visibility?orbits=1')).json();
    expect(vis.coverage_fraction).toBeGreaterThanOrEqual(0);
    expect(vis.coverage_fraction).toBeLessThanOrEqual(1);
    for (const w of vis.windows) {
      expect(w.end_s).toBeGreaterThanOrEqual(w.start_s);
      expect(w.max_elevation_deg).toBeGreaterThanOrEqual(vis.target.min_elevation_deg - 0.5);
    }

    // Coverage tab shows the red site marker.
    await page.getByTestId('overview-tab-coverage').click();
    await expect(page.getByTestId('map-ground-target')).toBeVisible({ timeout: 10_000 });

    // Clean up: unmark + restore the default constellation.
    await page.request.post('http://localhost:8001/ground_target', { data: { enabled: false } });
    await page.request.post('http://localhost:8001/constellation/single_iss');
  });

  test('comms config drives band/bandwidth + analytics tabs render', async ({ page }) => {
    // A dense constellation so the ground station gets contacts.
    const apply = await page.request.post('http://localhost:8001/orbit_design', {
      data: { altitude_km: 550, eccentricity: 0.001, inclination_deg: 53,
              raan_deg: 0, arg_perigee_deg: 0, mean_anomaly_deg: 0,
              planes: 8, sats_per_plane: 12, phasing: 1 },
    });
    expect(apply.ok()).toBeTruthy();

    // Comms-band catalog: monotone throughput + elevation tradeoff.
    const cat = await (await page.request.get('http://localhost:8001/comms_bands')).json();
    const byId = Object.fromEntries(cat.bands.map((b: { id: string }) => [b.id, b]));
    expect(byId.Ka.per_sat_mbps).toBeGreaterThan(byId.X.per_sat_mbps);
    expect(byId.Ka.min_elevation_deg).toBeGreaterThan(byId.UHF.min_elevation_deg);

    // Mark with Ka-band, elevation 5 → effective mask = max(5, Ka min 20) = 20.
    const mark = await page.request.post('http://localhost:8001/ground_target', {
      data: { enabled: true, band: 'Ka', elevation_mask_deg: 5, solar_bin: 5 },
    });
    expect(mark.ok()).toBeTruthy();
    await expect
      .poll(async () => {
        const s = await (await page.request.get('http://localhost:8001/state')).json();
        const g = s.ground_target;
        return g && g.band === 'Ka' && g.min_elevation_deg === 20
          && g.band_mbps_per_sat === 800 && g.solar_hist.length === 20
          && g.elevation_cdf.length > 0
          && g.aggregate_mbps === g.visible_sats * 800;
      }, { timeout: 10_000 })
      .toBe(true);

    // UI: analytics tabs render their charts.
    await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' });
    await page.getByTestId('overview-tab-solar').click();
    await expect(page.getByTestId('solar-histogram')).toBeVisible({ timeout: 10_000 });
    await page.getByTestId('overview-tab-bands').click();
    await expect(page.getByTestId('band-curves')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('band-curves').locator('svg path')).not.toHaveCount(0);
    await page.getByTestId('overview-tab-coverage').click();
    await expect(page.getByTestId('coverage-charts')).toBeVisible({ timeout: 10_000 });

    // Change the band live from the config (Designer tab).
    await page.getByTestId('overview-tab-designer').click();
    await page.getByTestId('band-S').click();
    await expect
      .poll(async () => {
        const s = await (await page.request.get('http://localhost:8001/state')).json();
        return s.ground_target?.band;
      }, { timeout: 10_000 })
      .toBe('S');

    // Clean up.
    await page.request.post('http://localhost:8001/ground_target', { data: { enabled: false } });
    await page.request.post('http://localhost:8001/constellation/single_iss');
  });
});
