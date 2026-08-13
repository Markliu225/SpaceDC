import { test, expect } from '@playwright/test';
import { dismissBuilder } from './twin';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));

test('orbit motion + page-triggered camera switch', async ({ page }) => {
  await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.dot.dot--ok')).toBeVisible({ timeout: 10_000 });
  await page.waitForFunction(() => {
    const v = document.getElementById('remote-video') as HTMLVideoElement | null;
    return !!v && v.videoWidth > 0;
  }, { timeout: 30_000 });

  // Give Kit a moment to consume its first state poll.
  await page.waitForTimeout(2500);
  const out = resolve(__dirname, '../test-results');
  mkdirSync(out, { recursive: true });

  // Capture overview
  await page.screenshot({ path: resolve(out, 'scene_overview.png') });

  // Show orbit motion: wait 5 s, snap again — satellite position should differ.
  await page.waitForTimeout(5000);
  await page.screenshot({ path: resolve(out, 'scene_overview_5s.png') });

  // Navigate to Satellite Twin — page mounts, changeCamera('satellite') fires.
  await page.getByRole('link', { name: 'Satellite Twin' }).click();
  await dismissBuilder(page);
  // Wait for Kit to process preset change + re-frame.
  await page.waitForTimeout(4000);
  await page.screenshot({ path: resolve(out, 'scene_satellite.png') });

  // Back to Overview to verify switch-back.
  await page.getByRole('link', { name: 'Overview', exact: true }).click();
  await page.waitForTimeout(4000);
  await page.screenshot({ path: resolve(out, 'scene_overview_return.png') });
});
