import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { login, USERS } from './helpers';

/** Spec 13: manager runs the orchestrator → approves a purchase request → PO created → supplier confirms and
 *  dispatches → staff posts the GRN → stock increases. */

async function token(request: APIRequestContext, role: keyof typeof USERS): Promise<{ token: string; supplierId: number | null }> {
  const [email, password] = USERS[role];
  const r = await request.post('/api/v1/auth/login', { data: { email, password } });
  expect(r.ok()).toBeTruthy();
  const j = await r.json();
  return { token: j.access_token, supplierId: j.user.supplier_id };
}

async function api<T>(request: APIRequestContext, t: string, path: string): Promise<T> {
  const r = await request.get(`/api/v1${path}`, { headers: { Authorization: `Bearer ${t}` } });
  expect(r.ok(), path).toBeTruthy();
  return (await r.json()) as T;
}

interface PR { id: number; product_id: number; sku: string; status: string; current_role: string | null; est_unit_price: number; po_id: number | null }

async function onHand(request: APIRequestContext, t: string, sku: string): Promise<number> {
  return (await api<{ stock: { on_hand: number } }>(request, t, `/stock/lookup?code=${encodeURIComponent(sku)}`)).stock.on_hand;
}

async function closeDialogs(page: Page) {
  const dlg = page.getByRole('dialog');
  if (await dlg.isVisible()) await dlg.getByRole('button', { name: 'Close' }).click();
}

test('full purchase cycle across manager, supplier and staff', async ({ page, request }) => {
  test.setTimeout(240_000);
  const mgr = await token(request, 'manager');
  const sup = await token(request, 'supplier');

  // 1. manager runs the orchestrator from AI Insights
  await login(page, 'manager');
  await page.goto('/insights');
  await page.getByRole('button', { name: 'Run full pipeline' }).click();
  await expect(page.getByRole('dialog', { name: 'Run result' })).toBeVisible({ timeout: 120_000 });
  await expect(page.getByRole('dialog').getByText('Auto-order')).toBeVisible();
  await closeDialogs(page);

  // 2. pick an AI request waiting for manager approval that the logged-in supplier can fulfil
  const pending = await api<{ items: PR[] }>(request, mgr.token, '/purchase-requests?mine=true&page_size=200');
  let chosen: PR | undefined;
  for (const pr of pending.items.filter((p) => p.current_role === 'manager')) {
    const offers = await api<{ supplier_id: number }[]>(request, mgr.token, `/supplier-products?product_id=${pr.product_id}`);
    if (offers.some((o) => o.supplier_id === sup.supplierId)) { chosen = pr; break; }
  }
  if (!chosen) {
    // no suitable AI suggestion today: raise one manually for a product this supplier sells (still manager-level)
    const offers = await api<{ product_id: number; unit_price: number }[]>(request, mgr.token, `/supplier-products?supplier_id=${sup.supplierId}`);
    const o = offers[0];
    const r = await request.post('/api/v1/purchase-requests', {
      headers: { Authorization: `Bearer ${mgr.token}` },
      data: { product_id: o.product_id, location_id: 1, qty: Math.ceil(8000 / o.unit_price), supplier_id: sup.supplierId, note: 'e2e' },
    });
    chosen = (await r.json()) as PR;
  }
  const before = await onHand(request, mgr.token, chosen.sku);

  // 3. approve it in the UI (edit-and-approve: route it to this supplier)
  await page.goto(`/approvals?pr=${chosen.id}`);
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Why the AI suggests this')).toBeVisible();
  await dialog.getByLabel('Suppliers').selectOption(String(sup.supplierId));
  await dialog.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeHidden();
  const approved = await api<PR & { final_qty: number }>(request, mgr.token, `/purchase-requests/${chosen.id}`);
  expect(approved.status).toBe('ORDERED');
  expect(approved.po_id).toBeTruthy();
  const poId = approved.po_id!;
  await page.goto(`/orders/${poId}`);
  await expect(page.getByText('Sent', { exact: true }).first()).toBeVisible();

  // 4. supplier confirms and dispatches in the portal
  await login(page, 'supplier');
  await page.goto(`/portal/orders/${poId}`);
  await page.getByRole('button', { name: 'Confirm order' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Submit' }).click();
  await expect(page.getByText('Confirmed', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Dispatch details' }).click();
  await page.getByRole('dialog').getByLabel('Tracking / LR number').fill('LR-E2E-01');
  await page.getByRole('dialog').getByRole('button', { name: 'Submit' }).click();
  await expect(page.getByText('Dispatched', { exact: true }).first()).toBeVisible();

  // 5. staff receives the goods (GRN)
  await login(page, 'staff');
  await page.goto(`/orders/${poId}`);
  await page.getByRole('button', { name: 'Receive goods (GRN)' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Post goods receipt' }).click();
  await expect(page.getByRole('status').filter({ hasText: /posted — stock updated/ })).toBeVisible();
  const po = await api<{ status: string }>(request, mgr.token, `/purchase-orders/${poId}`);
  expect(po.status).toBe('RECEIVED');

  // 6. stock increased by the ordered quantity
  await expect.poll(() => onHand(request, mgr.token, chosen!.sku)).toBeCloseTo(before + approved.final_qty, 3);
});
