import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { login, USERS } from '../e2e/helpers';

/** Regenerates the README screenshots in docs/screenshots from a seeded stack: `npm run screenshots`. */

const OUT = resolve(dirname(fileURLToPath(import.meta.url)), '../../../docs/screenshots');
mkdirSync(OUT, { recursive: true });

async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('.animate-pulse')).toHaveCount(0, { timeout: 20_000 });
  await page.waitForTimeout(800); // chart enter animations
}

async function shot(page: Page, name: string, path: string) {
  await page.goto(path);
  await settle(page);
  await page.screenshot({ path: `${OUT}/${name}.png` });
}

async function firstPendingAiRequest(request: APIRequestContext): Promise<number> {
  const [email, password] = USERS.manager;
  const t = (await (await request.post('/api/v1/auth/login', { data: { email, password } })).json()).access_token as string;
  const r = await request.get('/api/v1/purchase-requests?mine=true&page_size=50', { headers: { Authorization: `Bearer ${t}` } });
  const items = ((await r.json()) as { items: { id: number; created_by: number | null }[] }).items;
  const pr = items.find((p) => p.created_by === null) ?? items[0];
  expect(pr, 'a pending purchase request (run `make seed` first)').toBeTruthy();
  return pr.id;
}

test.use({ viewport: { width: 1366, height: 820 } });

test('README screenshots', async ({ page, request }) => {
  test.setTimeout(180_000);
  await login(page, 'manager');
  await shot(page, 'dashboard', '/');
  await shot(page, 'insights', '/insights');
  await shot(page, 'expiry', '/expiry');
  await page.goto(`/approvals?pr=${await firstPendingAiRequest(request)}`);
  await expect(page.getByRole('dialog')).toBeVisible();
  await settle(page);
  await page.screenshot({ path: `${OUT}/approval.png` });

  await login(page, 'supplier');
  await shot(page, 'portal', '/portal');

  await page.setViewportSize({ width: 360, height: 740 });
  await login(page, 'staff');
  await shot(page, 'mobile', '/');
});
