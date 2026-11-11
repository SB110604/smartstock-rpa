import { expect, test } from '@playwright/test';

/** Installability criteria (what Lighthouse checks): web manifest with name, start_url, display=standalone and
 *  192/512 icons; a registered service worker controlling the page; the app shell loads offline. */
test('PWA is installable and works offline', async ({ page, context, request }) => {
  // the service worker is registered only in production builds (nginx in Docker, or `npm run build && npm run preview`)
  const client = await request.get('/@vite/client');
  const devServer = client.ok() && (client.headers()['content-type'] ?? '').includes('javascript');
  test.skip(devServer, 'Vite dev server: run against a production build (E2E_BASE_URL=http://localhost:4173 after npm run preview)');
  const res = await request.get('/manifest.webmanifest');
  expect(res.ok()).toBeTruthy();
  const m = await res.json();
  expect(m.name).toBe('SmartStock RPA');
  expect(m.display).toBe('standalone');
  expect(m.start_url).toBe('/');
  const sizes = m.icons.map((i: { sizes: string }) => i.sizes);
  expect(sizes).toEqual(expect.arrayContaining(['192x192', '512x512']));
  for (const icon of m.icons) expect((await request.get(icon.src)).ok()).toBeTruthy();
  expect(m.icons.some((i: { purpose: string }) => i.purpose === 'maskable')).toBeTruthy();

  await page.goto('/login');
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
  await page.reload();
  expect(await page.evaluate(() => !!navigator.serviceWorker.controller)).toBeTruthy();
  await expect(page.locator('link[rel="manifest"]')).toHaveCount(1);

  await context.setOffline(true);
  await page.goto('/login');
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible();
  await context.setOffline(false);
});
