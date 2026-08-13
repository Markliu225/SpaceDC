import { test, expect } from '@playwright/test';
import { dismissBuilder } from './twin';

/** Roll-out solar array (redwire) — applying the design arrives STOWED,
 *  POST /solar_deploy animates the fraction ~12 s to full, production
 *  follows the fraction (retracted ⇒ zero solar even in sunlight), and the
 *  Configurator shows the deploy control only on the redwire design. */

// Later serial specs share the backend — always restore the default design.
test.afterEach(async ({ request }) => {
  await request.post('http://localhost:8001/designs/baseline/apply');
});

test('roll-out array deploys on command and drives solar production', async ({ page }) => {
  test.setTimeout(120_000);

  const api = page.request;
  await api.post('http://localhost:8001/designs/redwire/apply');

  // Applies stowed.
  await expect
    .poll(async () => (await (await api.get('http://localhost:8001/state')).json())
      .satellite.solar_deploy_frac, { timeout: 10_000 })
    .toBeLessThan(0.05);

  // The control is visible on the redwire design.
  await page.goto('http://localhost:5173/satellite', { waitUntil: 'domcontentloaded' });
  await dismissBuilder(page);
  const control = page.getByTestId('solar-deploy');
  await expect(control).toBeVisible({ timeout: 15_000 });
  await expect(control).toContainText('Deploy');

  // Click Deploy in the UI — the blanket reels out to 100% in ~12 s.
  await control.getByRole('button').click();
  await expect
    .poll(async () => (await (await api.get('http://localhost:8001/state')).json())
      .satellite.solar_deploy_frac, { timeout: 30_000 })
    .toBeGreaterThan(0.999);
  await expect(control).toContainText('Retract');

  // Retract via the API: production dies with the blanket reeled in
  // (deterministic — frac 0 forces solar_input_w to 0 in any sun phase).
  await api.post('http://localhost:8001/solar_deploy', { data: { action: 'retract' } });
  await expect
    .poll(async () => (await (await api.get('http://localhost:8001/state')).json())
      .satellite.solar_deploy_frac, { timeout: 30_000 })
    .toBeLessThan(0.002);
  const s = await (await api.get('http://localhost:8001/state')).json();
  expect(s.satellite.solar_input_w).toBe(0);

  // Baseline (rigid wings) never shows the control and applies deployed.
  await api.post('http://localhost:8001/designs/baseline/apply');
  await expect
    .poll(async () => (await (await api.get('http://localhost:8001/state')).json())
      .satellite.solar_deploy_frac, { timeout: 10_000 })
    .toBe(1);
  await expect(control).not.toBeVisible({ timeout: 15_000 });
});
