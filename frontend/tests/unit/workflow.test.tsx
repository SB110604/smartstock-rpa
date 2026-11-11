import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import OneClickApproval from '@/pages/auth/OneClickApproval';
import { alertLink, type AlertRow } from '@/pages/Alerts';
import { ExplanationPanel } from '@/pages/purchasing/Approvals';
import { mockFetch, renderApp } from './utils';

afterEach(() => vi.unstubAllGlobals());

const info = (action: 'approve' | 'reject') => ({
  action,
  level: 1,
  approver: 'Priya',
  expires_at: '2026-11-04T10:00:00+05:30',
  request: { id: 42, product: 'Toor Dal 1kg', qty: 120, unit: 'pack', supplier: 'Agarwal', est_total: 15360, reason_text: 'Forecast 120 units' },
});

describe('one-click approval page', () => {
  it('approves after a confirm click', async () => {
    const posted: unknown[] = [];
    mockFetch({
      'GET /approvals/token/abc': () => ({ json: info('approve') }),
      'POST /approvals/token/abc': (b) => { posted.push(b); return { json: { detail: 'Purchase request #42 is now approved' } }; },
    });
    renderApp(<OneClickApproval />, '/approval?token=abc');
    expect(await screen.findByText('Toor Dal 1kg')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(await screen.findByText('Purchase request #42 is now approved')).toBeInTheDocument();
    expect(posted).toEqual([{ reason: null }]);
  });

  it('requires a reason to reject', async () => {
    mockFetch({ 'GET /approvals/token/r1': () => ({ json: info('reject') }), 'POST /approvals/token/r1': () => ({ json: { detail: 'rejected' } }) });
    renderApp(<OneClickApproval />, '/approval?token=r1');
    const btn = await screen.findByRole('button', { name: 'Reject' });
    expect(btn).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Reason for rejecting'), 'Enough stock');
    expect(btn).toBeEnabled();
  });

  it('shows used/expired link errors', async () => {
    mockFetch({ 'GET /approvals/token/old': () => ({ status: 422, json: { detail: 'This approval link has expired', code: 'token_expired' } }) });
    renderApp(<OneClickApproval />, '/approval?token=old');
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('expired'));
  });
});

describe('explanation panel', () => {
  it('lists the inputs and supplier score bars', () => {
    render(
      <ExplanationPanel
        pr={{
          reason_text: 'Forecast 120 units over next 11 days',
          reason_json: { forecast_total: 120, lead_time_days: 4, safety_stock: 22, supplier: { name: 'Agarwal', breakdown: { price: 96, on_time: 88 } } },
        } as never}
      />,
    );
    expect(screen.getByText('Forecast 120 units over next 11 days')).toBeInTheDocument();
    expect(screen.getByText('Safety Stock')).toBeInTheDocument();
    expect(screen.getByText('On Time')).toBeInTheDocument();
  });
});

describe('alert links', () => {
  const base = { id: 1, severity: 'warning', product: null, message: '', data: null, status: 'open', resolution: null, created_at: '' } as const;
  it('routes alerts to the right page', () => {
    expect(alertLink({ ...base, type: 'three_way_mismatch', product_id: null, ref_type: 'purchase_order', ref_id: 9 } as AlertRow)).toBe('/orders/9');
    expect(alertLink({ ...base, type: 'expiry_critical', product_id: 3, ref_type: 'batch', ref_id: 5 } as AlertRow)).toBe('/expiry');
    expect(alertLink({ ...base, type: 'low_stock', product_id: 3, ref_type: null, ref_id: null } as AlertRow)).toBe('/products/3');
  });
});
