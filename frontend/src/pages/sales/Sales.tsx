import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Minus, Plus, Printer, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import type { Lookup, Sale } from '@/api/types';
import { ProductPicker } from '@/components/ProductPicker';
import { Button, Card, DataTable, Input, Modal, PageHeader, Pagination, Select, Tabs } from '@/components/ui';
import { useCurrentLocation } from '@/hooks/useCurrentLocation';
import { useLocations, usePublicSettings } from '@/hooks/useMasters';
import { api, type Page } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { formatDateTime, formatINR, formatNum } from '@/lib/format';
import { useToast } from '@/lib/toast';

interface CartLine {
  l: Lookup;
  qty: number;
  discount: number;
}

export function lineTotal(c: CartLine): number {
  return Math.round(c.qty * c.l.product.selling_price * (1 - c.discount / 100) * 100) / 100;
}

function Receipt({ sale, onClose }: { sale: Sale | null; onClose: () => void }) {
  const { t } = useTranslation();
  const settings = usePublicSettings();
  if (!sale) return null;
  return (
    <Modal
      open
      onClose={onClose}
      title={sale.invoice_no}
      footer={
        <>
          <Button variant="secondary" icon={<Printer className="h-4 w-4" />} onClick={() => window.print()}>
            {t('sales.print')}
          </Button>
          <Button onClick={onClose}>{t('sales.newBill')}</Button>
        </>
      }
    >
      <div className="print-area space-y-2 font-mono text-xs">
        <p className="text-center text-sm font-bold">{settings.data?.business.name}</p>
        <p className="text-center">
          {settings.data?.business.address}{' '}
          {settings.data?.business.gstin && `GSTIN ${settings.data.business.gstin}`}
        </p>
        <p>
          {formatDateTime(sale.sold_at)} · {sale.invoice_no}
        </p>
        <table className="w-full">
          <tbody>
            {sale.lines.map((l) => (
              <tr key={l.id}>
                <td className="py-0.5">
                  {l.product_name}
                  <br />
                  {formatNum(l.qty)} × {formatINR(l.unit_price)}
                  {l.discount_pct ? ` −${l.discount_pct}%` : ''}
                </td>
                <td className="text-right align-top">{formatINR(l.line_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="border-t border-dashed pt-1">
          <p className="flex justify-between">
            <span>{t('sales.taxable')}</span>
            <span>{formatINR(sale.subtotal)}</span>
          </p>
          <p className="flex justify-between">
            <span>GST</span>
            <span>{formatINR(sale.tax)}</span>
          </p>
          <p className="flex justify-between text-sm font-bold">
            <span>{t('common.total')}</span>
            <span>{formatINR(sale.total)}</span>
          </p>
        </div>
      </div>
    </Modal>
  );
}

function Billing() {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const locs = useLocations();
  const [locationId, setLocationId] = useCurrentLocation();
  const [cart, setCart] = useState<CartLine[]>([]);
  const [customer, setCustomer] = useState('');
  const [receipt, setReceipt] = useState<Sale | null>(null);
  const add = (l: Lookup) =>
    setCart((c) => {
      const i = c.findIndex((x) => x.l.product.id === l.product.id);
      if (i >= 0) return c.map((x, j) => (j === i ? { ...x, qty: x.qty + 1 } : x));
      return [...c, { l, qty: 1, discount: 0 }];
    });
  const update = (i: number, patch: Partial<CartLine>) =>
    setCart((c) => c.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const total = cart.reduce((s, c) => s + lineTotal(c), 0);
  const checkout = useMutation({
    mutationFn: () =>
      api.post<Sale>('/sales', {
        location_id: locationId,
        customer_name: customer || null,
        lines: cart.map((c) => ({ product_id: c.l.product.id, qty: c.qty, discount_pct: c.discount })),
      }),
    onSuccess: (s) => {
      setReceipt(s);
      setCart([]);
      setCustomer('');
      void qc.invalidateQueries({ queryKey: ['sales'] });
      void qc.invalidateQueries({ queryKey: ['products'] });
    },
    onError: (e) => toast.error(e),
  });
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card
        className="lg:col-span-2"
        title={t('sales.billing')}
        actions={
          <Select
            value={locationId ?? ''}
            onChange={(e) => setLocationId(Number(e.target.value))}
            aria-label={t('stock.location')}
            options={(locs.data ?? []).map((l) => ({ value: l.id, label: l.name }))}
          />
        }
      >
        <ProductPicker onPick={add} locationId={locationId} autoFocus placeholder={t('sales.scanHint')} />
        <ul className="mt-3 divide-y divide-slate-100 dark:divide-slate-800">
          {cart.map((c, i) => (
            <li key={c.l.product.id} className="flex flex-wrap items-center gap-2 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{c.l.product.name}</p>
                <p className="text-xs text-slate-500">
                  {formatINR(c.l.product.selling_price)} · {t('products.onHand')}{' '}
                  {formatNum(c.l.stock.on_hand)}
                </p>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  size="sm"
                  variant="secondary"
                  aria-label="-"
                  onClick={() => update(i, { qty: Math.max(1, c.qty - 1) })}
                >
                  <Minus className="h-3 w-3" />
                </Button>
                <input
                  className="input w-16 text-center"
                  type="number"
                  min="0.001"
                  step="any"
                  value={c.qty}
                  aria-label={t('common.qty')}
                  onChange={(e) => update(i, { qty: Math.max(0, Number(e.target.value)) })}
                />
                <Button
                  size="sm"
                  variant="secondary"
                  aria-label="+"
                  onClick={() => update(i, { qty: c.qty + 1 })}
                >
                  <Plus className="h-3 w-3" />
                </Button>
              </div>
              <input
                className="input w-16 text-right"
                type="number"
                min="0"
                max="100"
                value={c.discount}
                aria-label={t('sales.discount')}
                title={t('sales.discount')}
                onChange={(e) => update(i, { discount: Math.min(100, Math.max(0, Number(e.target.value))) })}
              />
              <span className="w-24 text-right text-sm font-semibold tabular-nums">
                {formatINR(lineTotal(c))}
              </span>
              <Button
                size="sm"
                variant="ghost"
                aria-label={t('common.remove')}
                onClick={() => setCart((x) => x.filter((_, j) => j !== i))}
              >
                <Trash2 className="h-4 w-4 text-rose-600" />
              </Button>
            </li>
          ))}
        </ul>
        {cart.length === 0 && (
          <p className="py-8 text-center text-sm text-slate-500">{t('sales.emptyCart')}</p>
        )}
      </Card>
      <Card title={t('sales.summary')}>
        <div className="space-y-3">
          <Input label={t('sales.customer')} value={customer} onChange={(e) => setCustomer(e.target.value)} />
          <p className="flex justify-between text-sm">
            <span>{t('sales.items')}</span>
            <span>{cart.length}</span>
          </p>
          <p className="flex justify-between text-xl font-bold">
            <span>{t('common.total')}</span>
            <span>{formatINR(total)}</span>
          </p>
          <p className="text-xs text-slate-500">{t('sales.taxIncluded')}</p>
          <Button
            className="w-full"
            size="md"
            loading={checkout.isPending}
            disabled={!cart.length || cart.some((c) => !(c.qty > 0)) || !locationId}
            onClick={() => checkout.mutate()}
          >
            {t('sales.checkout')}
          </Button>
        </div>
      </Card>
      <Receipt sale={receipt} onClose={() => setReceipt(null)} />
    </div>
  );
}

function History() {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const [q, setQ] = useState('');
  const [view, setView] = useState<Sale | null>(null);
  const data = useQuery({
    queryKey: ['sales', q, page],
    queryFn: () => api.get<Page<Sale>>('/sales', { q, page, page_size: 25 }),
  });
  return (
    <Card
      title={t('sales.history')}
      actions={
        <input
          className="input w-48"
          placeholder={t('common.search')}
          aria-label={t('common.search')}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
        />
      }
    >
      <DataTable<Sale>
        rows={data.data?.items}
        loading={data.isLoading}
        error={data.error}
        rowKey={(s) => s.id}
        onRowClick={setView}
        columns={[
          { key: 'invoice_no', header: t('sales.invoice'), className: 'font-mono text-xs' },
          { key: 'sold_at', header: t('common.date'), render: (s) => formatDateTime(s.sold_at) },
          {
            key: 'channel',
            header: t('sales.channel'),
            render: (s) => t(`sales.channel_${s.channel}`, { defaultValue: s.channel }),
          },
          { key: 'lines', header: t('sales.items'), align: 'right', render: (s) => s.lines.length },
          { key: 'tax', header: 'GST', align: 'right', render: (s) => formatINR(s.tax) },
          { key: 'total', header: t('common.total'), align: 'right', render: (s) => formatINR(s.total) },
        ]}
      />
      {data.data && <Pagination page={page} pageSize={25} total={data.data.total} onPage={setPage} />}
      <Receipt sale={view} onClose={() => setView(null)} />
    </Card>
  );
}

export default function Sales() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [sp, setSp] = useSearchParams();
  const tab = (sp.get('tab') as 'billing' | 'history') ?? 'billing';
  return (
    <div>
      <PageHeader title={t('nav.sales')} subtitle={t('sales.subtitle')} />
      <Tabs
        tabs={[
          { value: 'billing', label: t('sales.billing') },
          ...(can('sales.read') ? [{ value: 'history' as const, label: t('sales.history') }] : []),
        ]}
        value={tab}
        onChange={(v) => setSp({ tab: v }, { replace: true })}
      />
      {tab === 'billing' ? <Billing /> : <History />}
    </div>
  );
}
