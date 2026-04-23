import { test, expect } from '@playwright/test';

/**
 * End-to-end smoke test for Phase 1.
 * Preconditions (must be running):
 *   - backend @ :8001
 *   - Vite dev @ :5173
 *   - Kit streaming @ :49100
 */
test('full stack: web connects to backend + attempts Kit stream', async ({ page }) => {
  const logs: string[] = [];
  page.on('console', (msg) => logs.push(`[${msg.type()}] ${msg.text()}`));
  page.on('pageerror', (err) => logs.push(`[error] ${err.message}`));

  await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded', timeout: 30_000 });

  // Backend WS should connect and status dot should turn green within 5 s.
  await expect(page.locator('.dot.dot--ok')).toBeVisible({ timeout: 10_000 });

  // Sim time should advance (start with T+000:00:00, then change within 3 ticks).
  const firstTime = await page.locator('.shell__status span').first().innerText();
  await page.waitForTimeout(2500);
  const secondTime = await page.locator('.shell__status span').first().innerText();
  expect(secondTime).not.toBe(firstTime);

  // Status cards should populate.
  await expect(page.locator('.cards .card').first()).toBeVisible();
  const cardCount = await page.locator('.cards .card').count();
  expect(cardCount).toBeGreaterThanOrEqual(10);

  // SceneEmbed should mount — either the video container (stream ready) or placeholder.
  await expect(page.locator('.scene-embed')).toBeVisible();

  // Wait up to 20 s for stream to start OR explicit failure. "timeout" means still connecting.
  const finalStatus = await Promise.race([
    page.waitForSelector('#main-div[style*="display: block"]', { timeout: 20_000 }).then(() => 'ready'),
    page.waitForFunction(
      () => (document.querySelector('.scene-embed__placeholder')?.textContent ?? '').toLowerCase().includes('failed'),
      { timeout: 20_000 },
    ).then(() => 'failed'),
  ]).catch(() => 'timeout');

  console.log('final scene status:', finalStatus);
  console.log('console log tail:\n' + logs.slice(-30).join('\n'));

  // We pass if the stream reached ready (best case) OR reached failed (Kit unreachable — backend+UI still verified).
  expect(['ready', 'failed']).toContain(finalStatus);
});

test('task page: Start Task flows through backend state machine', async ({ page }) => {
  await page.goto('http://localhost:5173/task', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.dot.dot--ok')).toBeVisible({ timeout: 10_000 });
  await page.getByRole('button', { name: 'Start Task' }).click();
  // Task card should go from "no task" to showing a task id.
  await expect(page.locator('.task-card')).toContainText(/task-\d+/, { timeout: 5_000 });
});
