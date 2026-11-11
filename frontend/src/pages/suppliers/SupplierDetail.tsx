import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Pencil, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { Supplier, SupplierPrice } from '@/api/types';
import {
  Button,
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  Input,
  KeyValue,
  Modal,
  PageHeader,
  Select,
  SkeletonRows,
  StatusBadge,
} from '@/components/ui';
import { useProductOptions } from '@/hooks/useMasters';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { formatDate, formatINR, formatNum } from '@/lib/format';
import { useToast } from '@/lib/toast';
import { SupplierForm } from './Suppliers';

interface Score {
  total_score: number;
  price_score: number;
  on_time_pct: number;
  lead_score: number;
  quality_score: number;
  reject_pct: number;
  avg_lead_days: number;
  computed_at: string;
  orders_considered: number;
}
interface Detail {
  supplier: Supplier;
  score: Score | null;
  score_history: { computed_at: string; total_score: number; on_time_pct: number }[];
  prices: SupplierPrice[];
  purchase_orders: {
    id: number;
    po_no: string;
    status: string;
    order_date: string;
    expected_date: string | null;
    delivered_at: string | null;
    total: number;
  }[];
}

function PriceForm({
  supplierId,
  price,
  open,
  onClose,
}: {
  supplierId: number;
  price: SupplierPrice | null;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const products = useProductOptions();
  const [v, setV] = useState({
    product_id: '',
    unit_price: '',
    lead_time_days: '3',
    min_order_qty: '1',
    valid_till: '',
  });
  const [loadedFor, setLoadedFor] = useState<number | null | undefined>(undefined);
  if (open && loadedFor !== (price?.id ?? null)) {
    setLoadedFor(price?.id ?? null);
    setV(
      price
        ? {
            product_id: String(price.product_id),
            unit_price: String(price.unit_price),
            lead_time_days: String(price.lead_time_days),
            min_order_qty: String(price.min_order_qty),
            valid_till: price.valid_till ?? '',
          }
        : { product_id: '', unit_price: '', lead_time_days: '3', min_order_qty: '1', valid_till: '' },
    );
  }
  const save = useMutation({
    mutationFn: () =>
      api.post('/supplier-products', {
        supplier_id: supplierId,
        product_id: Number(v.product_id),
        unit_price: Number(v.unit_price),
        lead_time_days: Number(v.lead_time_days),
        min_order_qty: Number(v.min_order_qty),
        valid_till: v.valid_till || null,
      }),
    onSuccess: () => {
      toast.success(t('common.saved'));
      void qc.invalidateQueries({ queryKey: ['suppliers'] });
      onClose();
    },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('suppliers.priceEntry')}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            loading={save.isPending}
            disabled={!v.product_id || !v.unit_price}
            onClick={() => save.mutate()}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <Select
          className="col-span-2"
          label={t('nav.products')}
          value={v.product_id}
          disabled={!!price}
          placeholder="—"
          onChange={(e) => setV({ ...v, product_id: e.target.value })}
          options={(products.data ?? []).map((p) => ({ value: p.id, label: `${p.name} (${p.sku})` }))}
        />
        <Input
          label={t('suppliers.unitPrice')}
          type="number"
          step="0.01"
          value={v.unit_price}
          onChange={(e) => setV({ ...v, unit_price: e.target.value })}
        />
        <Input
          label={t('suppliers.leadTime')}
          type="number"
          value={v.lead_time_days}
          onChange={(e) => setV({ ...v, lead_time_days: e.target.value })}
        />
        <Input
          label={t('products.moq')}
          type="number"
          value={v.min_order_qty}
          onChange={(e) => setV({ ...v, min_order_qty: e.target.value })}
        />
        <Input
          label={t('suppliers.validTill')}
          type="date"
          value={v.valid_till}
          onChange={(e) => setV({ ...v, valid_till: e.target.value })}
        />
      </div>
    </Modal>
  );
}

export default function SupplierDetail() {
  const { id } = useParams();
  const { t } = useTranslation();
  const { can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [edit, setEdit] = useState(false);
  const [priceForm, setPriceForm] = useState<{ open: boolean; price: SupplierPrice | null }>({
    open: false,
    price: null,
  });
  const q = useQuery({
    queryKey: ['suppliers', 'detail', id],
    queryFn: () => api.get<Detail>(`/suppliers/${id}`),
  });
  const del = useMutation({
    mutationFn: (pid: number) => api.del(`/supplier-products/${pid}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['suppliers'] }),
    onError: (e) => toast.error(e),
  });
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <SkeletonRows rows={8} />;
  const { supplier: s, score, score_history, prices, purchase_orders } = q.data;
  const breakdown = score
    ? [
        { name: t('suppliers.price'), value: score.price_score },
        { name: t('suppliers.onTime'), value: score.on_time_pct },
        { name: t('suppliers.lead'), value: score.lead_score },
        { name: t('suppliers.quality'), value: score.quality_score },
      ]
    : [];
  const writable = can('suppliers.write');
  return (
    <div>
      <Link
        to="/suppliers"
        className="mb-2 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700"
      >
        <ArrowLeft className="h-4 w-4" /> {t('nav.suppliers')}
      </Link>
      <PageHeader
        title={s.name}
        subtitle={`${s.state}${s.gstin ? ` · ${s.gstin}` : ''}`}
        actions={
          writable && (
            <Button variant="secondary" icon={<Pencil className="h-4 w-4" />} onClick={() => setEdit(true)}>
              {t('common.edit')}
            </Button>
          )
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={t('products.details')}>
          <KeyValue
            items={[
              [t('suppliers.contact'), s.contact_name ?? '—'],
              [t('suppliers.phone'), s.phone ?? '—'],
              [t('auth.email'), s.email ?? '—'],
              [t('suppliers.terms'), `${s.payment_terms_days} d`],
              [t('suppliers.address'), s.address ?? '—'],
            ]}
          />
        </Card>
        <Card
          title={`${t('suppliers.score')}${score ? `: ${score.total_score.toFixed(1)} / 100` : ''}`}
          className="lg:col-span-2"
        >
          {score ? (
            <div className="grid gap-4 md:grid-cols-2">
              <div className="h-48">
                <ResponsiveContainer>
                  <BarChart data={breakdown} layout="vertical" margin={{ left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                    <XAxis type="number" domain={[0, 100]} fontSize={11} />
                    <YAxis type="category" dataKey="name" width={80} fontSize={11} />
                    <Tooltip formatter={(v: number) => v.toFixed(1)} />
                    <Bar dataKey="value" fill="#059669" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="h-48">
                {score_history.length > 1 ? (
                  <ResponsiveContainer>
                    <LineChart data={score_history.map((h) => ({ ...h, d: formatDate(h.computed_at) }))}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="d" fontSize={10} />
                      <YAxis domain={[0, 100]} fontSize={11} />
                      <Tooltip />
                      <Line
                        type="monotone"
                        dataKey="on_time_pct"
                        name={t('suppliers.onTime')}
                        stroke="#0ea5e9"
                        dot={false}
                      />
                      <Line
                        type="monotone"
                        dataKey="total_score"
                        name={t('suppliers.score')}
                        stroke="#059669"
                        dot={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <KeyValue
                    items={[
                      [t('suppliers.avgLead'), `${formatNum(score.avg_lead_days)} d`],
                      [t('suppliers.rejects'), `${formatNum(score.reject_pct)}%`],
                      [t('suppliers.ordersConsidered'), score.orders_considered],
                    ]}
                  />
                )}
              </div>
            </div>
          ) : (
            <EmptyState title={t('suppliers.noScore')} />
          )}
        </Card>
        <Card
          title={t('suppliers.priceList')}
          className="lg:col-span-3"
          actions={
            writable && (
              <Button
                size="sm"
                icon={<Plus className="h-4 w-4" />}
                onClick={() => setPriceForm({ open: true, price: null })}
              >
                {t('common.add')}
              </Button>
            )
          }
        >
          <DataTable<SupplierPrice>
            rows={prices}
            rowKey={(p) => p.id}
            empty={t('suppliers.noPrices')}
            columns={[
              {
                key: 'product_name',
                header: t('common.product'),
                render: (p) => (
                  <Link
                    className="text-brand-700 hover:underline dark:text-brand-400"
                    to={`/products/${p.product_id}`}
                  >
                    {p.product_name}
                  </Link>
                ),
              },
              { key: 'product_sku', header: t('products.sku'), className: 'font-mono text-xs' },
              {
                key: 'unit_price',
                header: t('suppliers.unitPrice'),
                align: 'right',
                render: (p) => formatINR(p.unit_price),
              },
              {
                key: 'lead_time_days',
                header: t('suppliers.leadTime'),
                align: 'right',
                render: (p) => `${p.lead_time_days} d`,
              },
              {
                key: 'min_order_qty',
                header: t('products.moq'),
                align: 'right',
                render: (p) => formatNum(p.min_order_qty),
              },
              {
                key: 'valid_till',
                header: t('suppliers.validTill'),
                render: (p) => formatDate(p.valid_till),
              },
              ...(writable
                ? [
                    {
                      key: 'actions',
                      header: '',
                      render: (p: SupplierPrice) => (
                        <div className="flex justify-end gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-label={t('common.edit')}
                            onClick={() => setPriceForm({ open: true, price: p })}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-label={t('common.delete')}
                            onClick={() => del.mutate(p.id)}
                          >
                            <Trash2 className="h-4 w-4 text-rose-600" />
                          </Button>
                        </div>
                      ),
                    },
                  ]
                : []),
            ]}
          />
        </Card>
        <Card title={t('suppliers.poHistory')} className="lg:col-span-3">
          <DataTable
            rows={purchase_orders}
            rowKey={(p) => p.id}
            empty={t('suppliers.noPos')}
            columns={[
              {
                key: 'po_no',
                header: 'PO',
                render: (p) => (
                  <Link
                    className="font-mono text-xs text-brand-700 hover:underline dark:text-brand-400"
                    to={`/orders/${p.id}`}
                  >
                    {p.po_no}
                  </Link>
                ),
              },
              { key: 'order_date', header: t('common.date'), render: (p) => formatDate(p.order_date) },
              {
                key: 'expected_date',
                header: t('orders.expected'),
                render: (p) => formatDate(p.expected_date),
              },
              {
                key: 'delivered_at',
                header: t('orders.delivered'),
                render: (p) => formatDate(p.delivered_at),
              },
              { key: 'total', header: t('common.total'), align: 'right', render: (p) => formatINR(p.total) },
              { key: 'status', header: t('common.status'), render: (p) => <StatusBadge status={p.status} /> },
            ]}
          />
        </Card>
      </div>
      <SupplierForm supplier={s} open={edit} onClose={() => setEdit(false)} />
      <PriceForm
        supplierId={s.id}
        price={priceForm.price}
        open={priceForm.open}
        onClose={() => setPriceForm({ open: false, price: null })}
      />
    </div>
  );
}
