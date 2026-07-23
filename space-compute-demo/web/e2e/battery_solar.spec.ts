import { test, expect } from '@playwright/test';

/**
 * R6 — battery config + attitude-driven solar collection, verified through the
 * twin Configurator UI. Backend + Vite base URLs are env-overridable so this
 * can run against an isolated verification stack:
 *   E2E_FRONT=http://localhost:5175 E2E_BACK=http://localhost:8002 \
 *     npx playwright test battery_solar
 * Defaults target the standard dev stack (:5173 / :8001).
 */
const FRONT = process.env.E2E_FRONT ?? 'http://localhost:5173';
const BACK = process.env.E2E_BACK ?? 'http://localhost:8001';

test.describe('battery config + attitude solar', () => {
  test('battery capacity readout follows chemistry × pack size', async ({ page }) => {
    await page.goto(`${FRONT}/satellite`, { waitUntil: 'domcontentloaded' });

    const capacity = page.getByText(/Capacity .* kWh/);
    await expect(capacity).toBeVisible({ timeout: 10_000 });

    // Chemistry: Li-ion NMC (250 Wh/kg). Pack: Large (32 kg) → 8.0 kWh.
    // `.last()` picks the innermost .relative that contains the label — i.e.
    // the ConfigDropdown root, not an outer rail container that also matches.
    const chemistry = page.locator('.relative', { hasText: 'Chemistry' }).last();
    const packSize = page.locator('.relative', { hasText: 'Pack size' }).last();

    async function pick(group: ReturnType<typeof page.locator>, optionRe: RegExp) {
      await group.getByRole('button').first().click();
      // Only one dropdown is ever open, so the listbox is page-unique.
      await page.getByRole('listbox').getByRole('button', { name: optionRe }).click();
    }

    // Option accessible names are `label + meta` with no separator, e.g.
    // "Large32 kg → 8.0 kWh" — anchor with ^ so "Large" ≠ "Extra Large".
    await pick(chemistry, /^Li-ion NMC/);
    await pick(packSize, /^Large/);
    await expect(capacity).toHaveText(/Capacity 8\.0 kWh/);

    // Lithium-Sulfur (400 Wh/kg) × Extra Large (60 kg) → 24.0 kWh.
    await pick(chemistry, /^Lithium-Sulfur/);
    await pick(packSize, /^Extra Large/);
    await expect(capacity).toHaveText(/Capacity 24\.0 kWh/);

    // LiFePO4 (160 Wh/kg) × Small (10 kg) → 1.6 kWh.
    await pick(chemistry, /^LiFePO4/);
    await pick(packSize, /^Small/);
    await expect(capacity).toHaveText(/Capacity 1\.6 kWh/);
  });

  test('solar-collection readout tracks the commanded attitude', async ({ page }) => {
    await page.request.post(`${BACK}/attitude_mode`, { data: { mode: 'free' } });
    await page.goto(`${FRONT}/satellite`, { waitUntil: 'domcontentloaded' });

    const control = page.getByTestId('attitude-control');
    await expect(control).toBeVisible({ timeout: 10_000 });
    const readout = control.locator('span.tabular').first();

    // The UI readout must equal the backend's live physics: sun-pointing holds
    // ~100 % whenever sunlit; eclipse forces 0. We assert the UI matches /state.
    async function expectReadoutMatchesBackend() {
      await expect
        .poll(async () => {
          const s = (await (await page.request.get(`${BACK}/state`)).json()).satellite;
          const want = !s.sunlit
            ? 'eclipse · 0%'
            : `${Math.round((s.solar_incidence ?? 0) * 100)}% incidence`;
          const got = (await readout.textContent())?.trim();
          return got === want;
        }, { timeout: 12_000 })
        .toBe(true);
    }

    await page.getByTestId('attitude-mode-sun').click();
    await expect(page.getByTestId('attitude-mode-sun')).toHaveAttribute('aria-pressed', 'true');
    await expectReadoutMatchesBackend();
    // When sunlit, sun-pointing is full power.
    {
      const s = (await (await page.request.get(`${BACK}/state`)).json()).satellite;
      if (s.sunlit) await expect(readout).toHaveText('100% incidence');
    }

    await page.getByTestId('attitude-mode-nadir').click();
    await expect(page.getByTestId('attitude-mode-nadir')).toHaveAttribute('aria-pressed', 'true');
    await expectReadoutMatchesBackend();

    await page.request.post(`${BACK}/attitude_mode`, { data: { mode: 'free' } });
  });

  test('capture configurator screenshot', async ({ page }) => {
    await page.goto(`${FRONT}/satellite`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('attitude-control')).toBeVisible({ timeout: 10_000 });
    await page.getByTestId('attitude-mode-sun').click();
    await page.waitForTimeout(1200);
    await page.screenshot({ path: 'e2e/__screens__/r6_configurator.png', fullPage: true });
  });
});
