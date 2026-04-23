import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));

/**
 * Screenshot-based visual check: wait for WebRTC stream ready, let it render
 * for ~3 s, then capture the video element's frame and assert it isn't uniform
 * black (which would mean Kit is running but scene failed to open).
 */
test('scene renders non-black content via WebRTC stream', async ({ page }) => {
  await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.dot.dot--ok')).toBeVisible({ timeout: 10_000 });

  // Wait up to 30 s for the shared <video> to receive frames.
  const gotFrames = await page.waitForFunction(() => {
    const v = document.getElementById('remote-video') as HTMLVideoElement | null;
    return !!v && v.videoWidth > 0;
  }, { timeout: 30_000 }).catch(() => null);
  console.log('video frames arrived:', !!gotFrames);

  // Always save a whole-page screenshot for visual inspection, regardless.
  const out = resolve(__dirname, '../test-results/scene.png');
  mkdirSync(dirname(out), { recursive: true });
  await page.screenshot({ path: out, fullPage: false });
  console.log('saved screenshot to', out);

  if (!gotFrames) {
    // Dump diagnostic state before failing.
    const diag = await page.evaluate(() => {
      const v = document.getElementById('remote-video') as HTMLVideoElement | null;
      return v ? {
        videoWidth: v.videoWidth,
        videoHeight: v.videoHeight,
        readyState: v.readyState,
        paused: v.paused,
        error: v.error?.message,
        networkState: v.networkState,
        srcObjectKind: (v as HTMLVideoElement & { srcObject?: MediaStream | null }).srcObject ? 'MediaStream' : 'null',
        trackCount: ((v as HTMLVideoElement & { srcObject?: MediaStream | null }).srcObject?.getTracks()?.length) ?? 0,
      } : { error: 'no video element' };
    });
    console.log('video diagnostics:', JSON.stringify(diag));
    throw new Error('video never received frames — see diagnostics above + test-results/scene.png');
  }

  await page.waitForTimeout(2000);

  // Sample central pixels from the <video> via canvas.
  const pixelStats = await page.evaluate(() => {
    const v = document.getElementById('remote-video') as HTMLVideoElement | null;
    if (!v || !v.videoWidth) return null;
    const canvas = document.createElement('canvas');
    canvas.width = 64; canvas.height = 36;
    const ctx = canvas.getContext('2d')!;
    ctx.drawImage(v, 0, 0, canvas.width, canvas.height);
    const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    let sum = 0, max = 0;
    for (let i = 0; i < data.length; i += 4) {
      const luma = 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
      sum += luma;
      if (luma > max) max = luma;
    }
    const avg = sum / (data.length / 4);
    return { avg, max, w: v.videoWidth, h: v.videoHeight };
  });

  console.log('video pixel stats:', JSON.stringify(pixelStats));
  expect(pixelStats).not.toBeNull();
  expect(pixelStats!.w).toBeGreaterThan(0);
  expect(pixelStats!.max).toBeGreaterThan(10);
});
