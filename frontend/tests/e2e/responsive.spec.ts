import { expect, test } from '@playwright/test';
import { login } from './helpers';

/** Spec 9 / phase 6: every page usable at 360 px — no horizontal page scroll, main content visible. */
const PAGES = {
  manager: ['/', '/products', '/stock', '/sales', '/expiry', '/alerts', '/approvals', '/orders', '/rfqs', '/returns', '/suppliers',
    '/insights', '/simulator', '/reports', '/imports', '/labels', '/settings', '/profile'],
  admin: ['/settings?tab=users', '/settings?tab=backups', '/audit', '/status', '/insights?tab=performance'],
  staff: ['/', '/stock?tab=counts', '/sales', '/orders'],
  supplier: ['/portal', '/portal/rfqs', '/portal/invoices'],
} as const;

for (const [role, pages] of Object.entries(PAGES)) {
  test(`${role} pages fit a 360 px screen`, async ({ page }) => {
    await login(page, role as keyof typeof PAGES);
    for (const path of pages) {
      await page.goto(path);
      await page.waitForLoadState('networkidle');
      await expect(page.locator('main h1').first()).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${path} scrolls horizontally by ${overflow}px`).toBeLessThanOrEqual(1);
    }
  });
}
