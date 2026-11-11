import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setTokens } from '@/lib/api';
import Expiry from '@/pages/stock/Expiry';
import { mockFetch, renderApp } from './utils';

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

const row = {
  batch_id: 7, product_id: 3, product: 'Amul Fresh Paneer 200g', sku: 'DRY-004', unit: 'pcs', batch_no: 'P1', location_id: 1,
  location: 'Main Store', expiry_date: '2026-11-04', days_to_expiry: 2, bucket: 'critical', qty: 18, value: 1332,
  avg_daily_sales: 3, projected_sell: 6, surplus: 12, at_risk: true, markdown_pct: 0, is_blocked: false, supplier_id: 3,
  suggested_markdown: 30, actions: ['markdown', 'return', 'write_off'], suggestion: 'Only 6 of 18 will sell before expiry — apply a 30% markdown.',
};

describe('Expiry page', () => {
  it('shows the suggestion and applies the suggested markdown', async () => {
    const posted: unknown[] = [];
    mockFetch({
      'GET /auth/me': () => ({ json: { id: 1, name: 'M', email: 'm@x.in', role: 'manager', permissions: ['stock.read', 'stock.approve', 'returns.manage'], language: 'en' } }),
      'GET /locations': () => ({ json: [{ id: 1, name: 'Main Store', type: 'store' }] }),
      'GET /expiry': () => ({ json: { groups: { expired: [], critical: [row], warning: [] },
        totals: { expired: { batches: 0, value: 0, at_risk: 0 }, critical: { batches: 1, value: 1332, at_risk: 1 }, warning: { batches: 0, value: 0, at_risk: 0 } },
        value_by_week: [{ week: '2026-W45', value: 1332 }] } }),
      'POST /stock/markdown': (b) => { posted.push(b); return { json: {} }; },
    });
    setTokens({ access_token: 'a', refresh_token: 'r' });
    renderApp(<Expiry />, '/expiry');
    expect(await screen.findByText(row.suggestion)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Markdown' })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Markdown' }));
    expect(screen.getByLabelText('Markdown %')).toHaveValue(30);
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(posted).toEqual([{ batch_id: 7, markdown_pct: 30 }]));
  });
});
