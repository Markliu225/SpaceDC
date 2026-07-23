import { test, expect } from '@playwright/test';

/**
 * Satellite attitude control — pointing modes vs reaction wheels are mutually
 * exclusive. Preconditions: backend @ :8001, Vite dev @ :5173. Kit optional
 * (the pose is applied in the Kit close-up; here we verify the state machine).
 */
test.describe('attitude control', () => {
  test('pointing mode and reaction wheels are mutually exclusive', async ({ page }) => {
    // Known start.
    await page.request.post('http://localhost:8001/attitude_mode', { data: { mode: 'free' } });
    await page.goto('http://localhost:5173/satellite', { waitUntil: 'domcontentloaded' });

    const control = page.getByTestId('attitude-control');
    await expect(control).toBeVisible({ timeout: 10_000 });

    // Select Sun-pointing → backend mode = sun, wheels zeroed, chip pressed.
    await page.getByTestId('attitude-mode-sun').click();
    await expect
      .poll(async () => {
        const s = await (await page.request.get('http://localhost:8001/state')).json();
        const sat = s.satellite;
        return sat.attitude_mode === 'sun'
          && (sat.attitude_spin_dps ?? [0, 0, 0]).every((r: number) => r === 0);
      }, { timeout: 10_000 })
      .toBe(true);
    await expect(page.getByTestId('attitude-mode-sun')).toHaveAttribute('aria-pressed', 'true');

    // Touch an X wheel → backend drops to free, X spins, Sun chip releases.
    await page.getByTestId('attitude-wheel-x').click();
    await expect
      .poll(async () => {
        const s = await (await page.request.get('http://localhost:8001/state')).json();
        const sat = s.satellite;
        return sat.attitude_mode === 'free' && (sat.attitude_spin_dps ?? [0])[0] > 0;
      }, { timeout: 10_000 })
      .toBe(true);
    await expect(page.getByTestId('attitude-mode-sun')).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByTestId('attitude-wheel-x')).toHaveAttribute('aria-pressed', 'true');

    // Selecting Nadir zeroes the wheel again.
    await page.getByTestId('attitude-mode-nadir').click();
    await expect
      .poll(async () => {
        const s = await (await page.request.get('http://localhost:8001/state')).json();
        const sat = s.satellite;
        return sat.attitude_mode === 'nadir'
          && (sat.attitude_spin_dps ?? [0, 0, 0]).every((r: number) => r === 0);
      }, { timeout: 10_000 })
      .toBe(true);

    // Unknown mode → 400.
    const bad = await page.request.post('http://localhost:8001/attitude_mode', { data: { mode: 'nonsense' } });
    expect(bad.status()).toBe(400);

    // Restore.
    await page.request.post('http://localhost:8001/attitude_mode', { data: { mode: 'free' } });
  });
});
