import type { Page } from '@playwright/test';

/**
 * The Satellite Twin page opens on the SATELLITE BUILDER (platform → structure
 * → payload slots → workload), which covers the viewport / Configurator /
 * telemetry layout until it is run or dismissed. Every spec that tests the
 * twin proper must therefore get past it first.
 *
 * Dismissing changes nothing about the flying satellite — the builder applies
 * only on Run — so tests keep whatever state they set up over the API.
 */
export async function dismissBuilder(page: Page): Promise<void> {
  const builder = page.getByTestId('satellite-builder');
  if (!await builder.isVisible({ timeout: 8_000 }).catch(() => false)) return;
  await page.getByRole('button', { name: 'close satellite builder' }).click();
  await builder.waitFor({ state: 'detached', timeout: 8_000 }).catch(() => {});
}

/** Navigate straight to the twin proper. */
export async function gotoTwin(
  page: Page, front = 'http://localhost:5173',
): Promise<void> {
  await page.goto(`${front}/satellite`, { waitUntil: 'domcontentloaded' });
  await dismissBuilder(page);
}
