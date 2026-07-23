import { test, expect } from '@playwright/test';

/**
 * Full-stack smoke test.
 * Preconditions: backend @ :8001, Vite dev @ :5173 (Kit optional).
 */
test('web connects to backend, sim advances, Overview renders', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded', timeout: 30_000 });

  // Backend WS connects → status dot turns green.
  await expect(page.locator('.dot.dot--ok')).toBeVisible({ timeout: 10_000 });

  // Sim time advances.
  const firstTime = await page.locator('.shell__status span').first().innerText();
  await page.waitForTimeout(2500);
  const secondTime = await page.locator('.shell__status span').first().innerText();
  expect(secondTime).not.toBe(firstTime);

  // Nav is trimmed to the two live pages.
  await expect(page.getByRole('link', { name: 'Overview' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Satellite Twin' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Mission' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Task' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Control' })).toHaveCount(0);

  // Overview renders its KPI row + the orbit designer workbench.
  await expect(page.getByText('Total Satellites', { exact: false })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('overview-tab-designer')).toBeVisible();

  expect(errors, `page errors: ${errors.join('; ')}`).toHaveLength(0);
});

