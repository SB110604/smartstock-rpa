import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Lookup } from '@/api/types';
import { DataTable, StatusBadge } from '@/components/ui';
import Login from '@/pages/auth/Login';
import { lineTotal } from '@/pages/sales/Sales';
import { mockFetch, renderApp } from './utils';

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

const me = { id: 1, name: 'Admin', email: 'admin@demo.in', role: 'admin', permissions: ['products.read'], language: 'en' };

describe('Login', () => {
  it('asks for the authenticator code when the server requires 2FA', async () => {
    const calls: unknown[] = [];
    mockFetch({
      'POST /auth/login': (body) => {
        calls.push(body);
        const b = body as { totp_code?: string };
        return b.totp_code
          ? { json: { access_token: 'a', refresh_token: 'r', user: me } }
          : { status: 401, json: { detail: 'Enter the 6-digit code', code: 'totp_required' } };
      },
    });
    renderApp(<Login />, '/login');
    await userEvent.type(screen.getByLabelText('Email'), 'admin@demo.in');
    await userEvent.type(screen.getByLabelText('Password'), 'Admin@123');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    const code = await screen.findByLabelText('Authentication code');
    await userEvent.type(code, '123456');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]).toMatchObject({ totp_code: '123456' });
    await waitFor(() => expect(localStorage.getItem('ss.tokens')).toContain('"access_token":"a"'));
  });

  it('shows the server error for wrong credentials', async () => {
    mockFetch({ 'POST /auth/login': () => ({ status: 401, json: { detail: 'Incorrect email or password', code: 'invalid_credentials' } }) });
    renderApp(<Login />, '/login');
    await userEvent.type(screen.getByLabelText('Email'), 'x@demo.in');
    await userEvent.type(screen.getByLabelText('Password'), 'nope');
    fireEvent.submit(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password');
  });

  it('validates the email before calling the API', async () => {
    const f = mockFetch({});
    renderApp(<Login />, '/login');
    await userEvent.type(screen.getByLabelText('Email'), 'not-an-email');
    await userEvent.type(screen.getByLabelText('Password'), 'x');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('Enter a valid email')).toBeInTheDocument();
    expect(f).not.toHaveBeenCalledWith(expect.stringContaining('/auth/login'), expect.anything());
  });
});

describe('DataTable', () => {
  const cols = [{ key: 'name', header: 'Name' }];
  it('renders skeleton, empty and rows states', () => {
    const { rerender } = render(<DataTable columns={cols} rows={undefined} loading rowKey={(r: { id: number }) => r.id} />);
    expect(screen.getByLabelText('loading')).toBeInTheDocument();
    rerender(<DataTable columns={cols} rows={[]} rowKey={(r: { id: number }) => r.id} empty="Nothing" />);
    expect(screen.getByText('Nothing')).toBeInTheDocument();
    rerender(<DataTable columns={cols} rows={[{ id: 1, name: 'Rice' }]} rowKey={(r) => r.id} />);
    expect(screen.getByText('Rice')).toBeInTheDocument();
  });

  it('supports select-all', async () => {
    const onSelect = vi.fn();
    render(
      <DataTable columns={cols} rows={[{ id: 1, name: 'A' }, { id: 2, name: 'B' }]} rowKey={(r) => r.id}
        selectable selected={new Set()} onSelect={onSelect} />,
    );
    await userEvent.click(screen.getByLabelText('select all'));
    expect([...onSelect.mock.calls[0][0]]).toEqual([1, 2]);
  });

  it('shows the error state with retry', async () => {
    const retry = vi.fn();
    render(<DataTable columns={cols} rows={undefined} error={new Error('boom')} onRetry={retry} rowKey={() => 1} />);
    expect(screen.getByRole('alert')).toHaveTextContent('boom');
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(retry).toHaveBeenCalled();
  });
});

describe('billing', () => {
  it('computes line totals with discount', () => {
    const l = { product: { selling_price: 120 } } as Lookup;
    expect(lineTotal({ l, qty: 3, discount: 10 })).toBe(324);
    expect(lineTotal({ l, qty: 0.5, discount: 0 })).toBe(60);
  });

  it('translates workflow statuses', () => {
    render(<StatusBadge status="PENDING_APPROVAL" />);
    expect(screen.getByText('Pending approval')).toBeInTheDocument();
  });
});
