import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChatPanel } from '@/components/ChatPanel';
import Simulator from '@/pages/insights/Simulator';
import { mockFetch, renderApp } from './utils';

afterEach(() => vi.unstubAllGlobals());

describe('chat panel', () => {
  it('sends an example question and shows the answer', async () => {
    const history: { role: string; content: string }[] = [];
    mockFetch({
      'GET /assistant/history': () => ({ json: history }),
      'GET /assistant/status': () => ({ json: { llm: { provider: 'none', configured: false } } }),
      'POST /assistant/chat': (b) => {
        const m = (b as { message: string }).message;
        history.push({ role: 'user', content: m }, { role: 'assistant', content: '• Basmati Rice 5kg: 42 pack on hand' });
        return { json: { reply: 'ok', mode: 'rules', tool_calls: [] } };
      },
    });
    renderApp(<ChatPanel open onClose={() => undefined} />);
    expect(await screen.findByText('Rule-based mode (no LLM configured)')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'How much rice is left?' }));
    expect(await screen.findByText('• Basmati Rice 5kg: 42 pack on hand')).toBeInTheDocument();
  });
});

describe('simulator', () => {
  it('posts the assumptions and renders per-product deltas', async () => {
    const posted: unknown[] = [];
    mockFetch({
      'GET /categories': () => ({ json: [] }),
      'GET /suppliers': () => ({ json: { items: [{ id: 2, name: 'Shah Distributors' }], total: 1, page: 1, page_size: 500 } }),
      'POST /simulator': (b) => {
        posted.push(b);
        return { json: { totals: { order_value: 12000, holding_cost: 300, ordering_cost: 1500, stockout_risk: 1, reorder_now: 2, ss_change: 5 },
          products: [{ product_id: 1, product: 'Sugar 1kg', unit: 'kg', supplier: 'Agarwal', supplier_changed: true, no_supplier: false,
            current: { rop: 50, ss: 10, eoq: 300, order_qty: 300 }, new: { rop: 80, ss: 16, eoq: 360, order_qty: 375, lead_days: 5 },
            cover_days: 2.5, stockout_risk: true, cost: { purchase: 15000, holding: 120, ordering: 500 } }] } };
      },
    });
    renderApp(<Simulator />);
    await userEvent.clear(screen.getByLabelText('Demand change %'));
    await userEvent.type(screen.getByLabelText('Demand change %'), '30');
    await userEvent.click(screen.getByRole('button', { name: 'Run simulation' }));
    expect(await screen.findByText('Sugar 1kg')).toBeInTheDocument();
    expect(screen.getByText('(+30)')).toBeInTheDocument();
    await waitFor(() => expect(posted[0]).toMatchObject({ demand_change_pct: 30, service_level: 0.95 }));
  });
});
