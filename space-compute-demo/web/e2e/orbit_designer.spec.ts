import { test, expect } from '@playwright/test';

/**
 * Orbit designer + Singapore ground-station visibility (Overview page).
 * Preconditions (must be running):
 *   - backend @ :8001
 *   - Vite dev @ :5173
 * Kit is NOT required.
 *
 * The right column carries THREE tabs — Design · Coverage · Solar. The
 * ground-station controls (mark toggle · elevation mask · comms band ·
 * analyze) sit in COVERAGE because they drive its charts; the solar bin
 * control sits in SOLAR with the histogram it bins.
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
    // Walker: ONE ring per plane, fanned backend-side so no consumer has to
    // rotate a base ring itself. Ring 0 stays the legacy single-ring payload.
    expect(detail.rings_eci_km).toHaveLength(3);
    expect(detail.rings_eci_km).toHaveLength(detail.planes);
    expect(detail.rings_eci_km[0]).toEqual(detail.ring_eci_km);
    for (const ring of detail.rings_eci_km) {
      expect(ring).toHaveLength(detail.ring_eci_km.length);
    }

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

  test('designs a sun-synchronous stack and refuses unimplemented options', async ({ page }) => {
    // SSO fixes every orbital element except altitude: `layers` shells,
    // stacked low → high, one plane each.
    const sso = await page.request.post('http://localhost:8001/orbit_design', {
      data: { mode: 'sso', alt_min_km: 500, alt_max_km: 700,
              layers: 3, sats_per_plane: 8, phasing: 1 },
    });
    expect(sso.ok()).toBeTruthy();
    const body = await sso.json();
    expect(body.ok).toBe(true);
    expect(body.active).toBe('custom_design');
    expect(body.mode).toBe('sso');
    expect(body.sso.total_sats).toBe(24);
    expect(body.sso.shells).toHaveLength(3);

    // The sun-synchronous condition makes inclination rise with altitude and
    // keeps every shell near-polar retrograde (textbook: 500 km → 97.40°).
    type Shell = {
      altitude_km: number; inclination_deg: number;
      raan_deg: number; beta_deg: number; sats: number;
    };
    const shells: Shell[] = body.sso.shells;
    expect(shells[0].altitude_km).toBeCloseTo(500, 3);
    expect(shells[shells.length - 1].altitude_km).toBeCloseTo(700, 3);
    expect(shells[0].inclination_deg).toBeCloseTo(97.4, 0);
    for (let i = 1; i < shells.length; i += 1) {
      expect(shells[i].altitude_km).toBeGreaterThan(shells[i - 1].altitude_km);
      expect(shells[i].inclination_deg).toBeGreaterThan(shells[i - 1].inclination_deg);
    }
    for (const s of shells) {
      expect(s.inclination_deg).toBeGreaterThan(96);
      expect(s.inclination_deg).toBeLessThan(101);
      expect(s.sats).toBe(8);
    }

    // THE dawn-dusk invariant: every shell stands on the SAME plane, the one
    // whose normal points at the sun. A shared RAAN is what separates a
    // terminator stack from the k*360/layers fan it replaced -- the shells may
    // differ ONLY in altitude and the SSO inclination that goes with it.
    expect(new Set(shells.map((s) => s.raan_deg)).size).toBe(1);
    expect(shells[0].raan_deg).toBeCloseTo((body.sso.sun_ra_deg + 90) % 360, 4);
    expect(body.sso.raan_deg).toBeCloseTo(shells[0].raan_deg, 6);
    expect(body.sso.ltan_hours).toBe(18);
    expect(body.sso.sun_ra_deg).toBeGreaterThanOrEqual(0);
    expect(body.sso.sun_ra_deg).toBeLessThan(360);

    // beta (the sun's elevation above the plane) is REPORTED, never forced:
    // beta = 90 deg only when the season cooperates, so the API says what it
    // really is instead of pretending the plane is always the terminator.
    expect(body.sso.beta_deg).toBeCloseTo(shells[0].beta_deg, 6);
    for (const s of shells) {
      expect(Number.isFinite(s.beta_deg)).toBe(true);
      expect(Math.abs(s.beta_deg)).toBeLessThanOrEqual(90);
    }

    // The stack goes live like any other design: 3 shells x 8 satellites.
    await expect
      .poll(async () => {
        const s = await (await page.request.get('http://localhost:8001/state')).json();
        return s.constellation?.constellation_id === 'custom_design'
          && s.constellation?.total === 24;
      }, { timeout: 10_000 })
      .toBe(true);

    // Each shell is propagated as its OWN ring (own altitude, own SSO
    // inclination, shared RAAN), and the rings come out concentric.
    const detail = await (await page.request.get(
      'http://localhost:8001/constellations/custom_design')).json();
    const rings: number[][][] = detail.rings_eci_km;
    expect(rings).toHaveLength(shells.length);
    expect(rings[0]).toEqual(detail.ring_eci_km);

    const unitNormal = (ring: number[][]): number[] => {
      const a = ring[0];
      const b = ring[Math.floor(ring.length / 3)];
      const c = ring[Math.floor((2 * ring.length) / 3)];
      const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
      const v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
      const n = [u[1] * v[2] - u[2] * v[1],
                 u[2] * v[0] - u[0] * v[2],
                 u[0] * v[1] - u[1] * v[0]];
      const len = Math.hypot(n[0], n[1], n[2]);
      return [n[0] / len, n[1] / len, n[2] / len];
    };
    const dot = (p: number[], q: number[]) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2];
    const degOff = (p: number[], q: number[]) =>
      (Math.acos(Math.min(1, Math.abs(dot(p, q)))) * 180) / Math.PI;

    // ONE plane: every shell normal within 1.5 deg of the innermost shell's.
    // The residual is the real per-altitude inclination spread (~0.8 deg over
    // 500-700 km), which must NOT be flattened away.
    const normals = rings.map(unitNormal);
    for (const n of normals) {
      expect(degOff(n, normals[0])).toBeLessThan(1.5);
    }
    // ...at genuinely different altitudes: three shells, not one ring copied.
    const radius = (ring: number[][]) => Math.hypot(ring[0][0], ring[0][1], ring[0][2]);
    for (let i = 1; i < rings.length; i += 1) {
      expect(radius(rings[i])).toBeGreaterThan(radius(rings[i - 1]));
    }

    // The sky frame the renderers light with is broadcast every tick, in the
    // same frame and at the same instant as the fleet ECI it carries.
    const sky = await (await page.request.get('http://localhost:8001/state')).json();
    const sun: number[] = sky.constellation.sun_unit_teme;
    expect(sun).toHaveLength(3);
    expect(Math.hypot(sun[0], sun[1], sun[2])).toBeCloseTo(1, 6);
    expect(sky.constellation.gmst_rad).toBeGreaterThanOrEqual(0);
    expect(sky.constellation.gmst_rad).toBeLessThan(2 * Math.PI);

    // ...and it is the SAME sun the plane was designed against. beta is the
    // sun's elevation above the plane, sin beta = h.s with the orbit normal
    // h = (sin i sin W, -sin i cos W, cos i). Read beta off the served ring
    // GEOMETRY and off the reported ELEMENTS, both against the BROADCAST sun:
    // they agree to a hundredth of a degree. That identity between the frame
    // the design lives in and the frame the renderers light with is what makes
    // "the ring lies on the rendered terminator" true by construction rather
    // than by coincidence.
    const geoBeta = normals.map(
      (n) => (Math.asin(Math.min(1, Math.abs(dot(n, sun)))) * 180) / Math.PI);
    for (let i = 0; i < rings.length; i += 1) {
      const inc = (shells[i].inclination_deg * Math.PI) / 180;
      const node = (shells[i].raan_deg * Math.PI) / 180;
      const h = [Math.sin(inc) * Math.sin(node), -Math.sin(inc) * Math.cos(node), Math.cos(inc)];
      const elementBeta = (Math.asin(Math.max(-1, Math.min(1, dot(h, sun)))) * 180) / Math.PI;
      expect(geoBeta[i]).toBeCloseTo(Math.abs(elementBeta), 1);
    }

    // The reported beta is measured, not asserted: shell to shell it moves
    // exactly as the ring geometry does. (The absolute values differ by the
    // sun's own motion between the epoch beta is solved at and the "now" the
    // rings are lit by, but the SPREAD across shells is drift-free.) A beta
    // pinned at 90 deg -- an inclination or RAAN fudged to force "on the
    // terminator" -- would flatten this spread and fail here.
    for (let i = 1; i < rings.length; i += 1) {
      const dGeo = geoBeta[i] - geoBeta[i - 1];
      const dReported = Math.abs(shells[i].beta_deg) - Math.abs(shells[i - 1].beta_deg);
      expect(Math.sign(dGeo)).toBe(Math.sign(dReported));
      expect(dGeo).toBeCloseTo(dReported, 1);
    }

    // LTAN picks which terminator crossing the ascending node sits on:
    // Omega = alpha_sun + 15 deg (LTAN - 12). Dawn is the mirror of dusk.
    const dawn = await page.request.post('http://localhost:8001/orbit_design', {
      data: { mode: 'sso', alt_min_km: 500, alt_max_km: 700,
              layers: 3, sats_per_plane: 8, phasing: 1, ltan_hours: 6 },
    });
    expect(dawn.ok()).toBeTruthy();
    const dawnSso = (await dawn.json()).sso;
    expect(dawnSso.ltan_hours).toBe(6);
    expect(new Set(dawnSso.shells.map((s: Shell) => s.raan_deg)).size).toBe(1);
    expect(dawnSso.raan_deg).toBeCloseTo((dawnSso.sun_ra_deg + 270) % 360, 4);

    // Noon is not a dawn-dusk orbit, so it is refused rather than silently
    // rounded to one of the two crossings.
    const noon = await page.request.post('http://localhost:8001/orbit_design', {
      data: { mode: 'sso', ltan_hours: 12 },
    });
    expect(noon.status()).toBe(422);
    expect(JSON.stringify(await noon.json())).toMatch(/ltan_hours/i);

    // GET reports the pattern in force, the propagator catalog (four models,
    // exactly one implemented) and the mission window.
    const info = await (await page.request.get('http://localhost:8001/orbit_design')).json();
    expect(info.mode).toBe('sso');
    expect(info.propagator).toBe('sgp4');
    expect(info.propagators.map((p: { id: string }) => p.id))
      .toEqual(['sgp4', 'twobody', 'j2', 'hpop']);
    const implemented = info.propagators.filter((p: { implemented: boolean }) => p.implemented);
    expect(implemented).toHaveLength(1);
    expect(implemented[0].id).toBe('sgp4');
    for (const key of ['epoch_utc', 'start_utc', 'end_utc']) {
      expect(Number.isFinite(Date.parse(info[key]))).toBe(true);
    }
    expect(info.window_s).toBeGreaterThan(0);
    expect(info.window_s).toBeCloseTo(
      (Date.parse(info.end_utc) - Date.parse(info.start_utc)) / 1000, 3);

    // Only SGP4 is implemented, and TLE import is not wired up.
    const j2 = await page.request.post('http://localhost:8001/orbit_design', {
      data: { propagator: 'j2' },
    });
    expect(j2.status()).toBe(422);
    expect(JSON.stringify(await j2.json())).toMatch(/not implemented/i);
    const custom = await page.request.post('http://localhost:8001/orbit_design', {
      data: { mode: 'custom' },
    });
    expect(custom.status()).toBe(422);
    expect(JSON.stringify(await custom.json())).toMatch(/not implemented/i);

    // Clean up: restore the default constellation.
    await page.request.post('http://localhost:8001/constellation/single_iss');
  });

  test('marks Singapore and reports live + analyzed communication visibility', async ({ page }) => {
    await page.request.post('http://localhost:8001/ground_target', { data: { enabled: false } });
    await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' });

    // The ground-station controls live in the tab whose charts they drive.
    await page.getByTestId('overview-tab-coverage').click();

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

    // Same tab: the map shows the red site marker.
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
    // Whole-constellation energy harvest sits underneath the histogram.
    await expect(page.getByTestId('energy-harvest')).toBeVisible({ timeout: 10_000 });

    // The bin control moved here with the histogram it bins: 10 % bins → 10 bars.
    await page.getByTestId('solar-bin-10').click();
    await expect
      .poll(async () => {
        const s = await (await page.request.get('http://localhost:8001/state')).json();
        return s.ground_target?.solar_hist?.length;
      }, { timeout: 10_000 })
      .toBe(10);

    await page.getByTestId('overview-tab-coverage').click();
    await expect(page.getByTestId('coverage-charts')).toBeVisible({ timeout: 10_000 });

    // Change the band live from the ground-station controls (Coverage tab).
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

  test('the Design tab fits 1440x900 with no inner scrollbar', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' });
    await page.getByTestId('overview-tab-designer').click();
    await expect(page.getByTestId('orbit-elements')).toBeVisible({ timeout: 15_000 });

    // Worst content overflow of any clipping/scrolling ancestor of the ACTIVE
    // readout — i.e. the designer body. <= 1px (rounding) means no scrollbar.
    const overflow = () => page.getByTestId('orbit-elements').evaluate((node) => {
      let worst = 0;
      let el: HTMLElement | null = node.parentElement;
      for (let i = 0; el && el !== document.body && i < 8; i += 1) {
        const oy = getComputedStyle(el).overflowY;
        if (oy === 'auto' || oy === 'scroll' || oy === 'hidden') {
          worst = Math.max(worst, el.scrollHeight - el.clientHeight);
        }
        el = el.parentElement;
      }
      return worst;
    });

    // …in every pattern mode: the PARAMETERS block is mode-dependent, so each
    // one has to hold the height budget on its own.
    for (const mode of ['walker', 'sso', 'custom']) {
      await page.getByTestId(`pattern-${mode}`).click();
      await expect.poll(overflow, { timeout: 5_000 }).toBeLessThanOrEqual(1);
    }
  });
});
