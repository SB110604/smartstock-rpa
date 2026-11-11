import { useQuery } from '@tanstack/react-query';
import { AlertTriangle } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Card, DataTable, PageHeader, Pagination, SearchBox, StatusBadge } from '@/components/ui';
import { api, type Page } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { formatDate, formatINR } from '@/lib/format';

export interface PORow {
  id: number;
  po_no: string;
  status: string;
  supplier_id: number;
  supplier: string;
  location: string;
  order_date: string;
  expected_date: string | null;
  predicted_date: string | null;
  supplier_eta: string | null;
  is_interstate: boolean;
  subtotal: number;
  cgst: number;
  sgst: number;
  igst: number;
  total: number;
  tracking_ref: string | null;
  courier_name: string | null;
  courier_status: string | null;
  delivered_at: string | null;
  rejection_reason: string | null;
  late: boolean;
  lines_count: number;
}

const FILTERS = [
  { value: '', key: 'all' },
  { value: 'SENT,CONFIRMED,DISPATCHED,PARTIALLY_RECEIVED', key: 'open' },
  { value: 'SENT', key: 'sent' },
  { value: 'DISPATCHED', key: 'dispatched' },
  { value: 'INVOICED', key: 'invoiced' },
  { value: 'CLOSED', key: 'closed' },
  { value: 'late', key: 'late' },
];

export function POTable({ rows, loading, error, onOpen }: { rows?: PORow[]; loading?: boolean; error?: unknown; onOpen: (r: PORow) => void }) {
  const { t } = useTranslation();
  return (
    <DataTable<PORow>
      rows={rows}
      loading={loading}
      error={error}
      rowKey={(r) => r.id}
      onRowClick={onOpen}
      empty={t('orders.empty')}
      columns={[
        { key: 'po_no', header: 'PO', className: 'font-mono text-xs' },
        { key: 'supplier', header: t('common.supplier'), render: (r) => <span className="whitespace-normal">{r.supplier}</span> },
        { key: 'order_date', header: t('common.date'), render: (r) => formatDate(r.order_date) },
        { key: 'expected_date', header: t('orders.expected'), render: (r) => <span className="flex items-center gap-1">{formatDate(r.supplier_eta ?? r.expected_date)}{r.late && <AlertTriangle className="h-3.5 w-3.5 text-rose-600" aria-label={t('orders.late')} />}</span> },
        { key: 'total', header: t('common.total'), align: 'right', render: (r) => formatINR(r.total) },
        { key: 'status', header: t('common.status'), render: (r) => <StatusBadge status={r.status} /> },
      ]}
    />
  );
}

export default function Orders() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [sp, setSp] = useSearchParams();
  const [q, setQ] = useState(() => sp.get('q') ?? '');
  const [page, setPage] = useState(1);
  const filter = sp.get('f') ?? (user?.role === 'staff' ? 'SENT,CONFIRMED,DISPATCHED,PARTIALLY_RECEIVED' : '');
  const params = filter === 'late' ? { late: true } : { status: filter };
  const list = useQuery({
    queryKey: ['orders', filter, q, page],
    queryFn: () => api.get<Page<PORow>>('/purchase-orders', { ...params, q, page, page_size: 25 }),
  });
  return (
    <div>
      <PageHeader title={t('nav.orders')} subtitle={t('orders.subtitle')} />
      <div className="mb-3 flex gap-1.5 overflow-x-auto pb-1">
        {FILTERS.map((f) => (
          <button key={f.key} onClick={() => { setSp(f.value ? { f: f.value } : {}); setPage(1); }}
            className={`whitespace-nowrap rounded-full border px-3 py-1 text-xs font-medium ${filter === f.value ? 'border-brand-600 bg-brand-600 text-white' : 'border-slate-300 text-slate-600 dark:border-slate-700 dark:text-slate-300'}`}>
            {t(`orders.filter_${f.key}`)}
          </button>
        ))}
      </div>
      <Card title={<SearchBox value={q} onChange={(v) => { setQ(v); setPage(1); }} />}>
        <POTable rows={list.data?.items} loading={list.isLoading} error={list.error} onOpen={(r) => navigate(`/orders/${r.id}`)} />
        {list.data && <Pagination page={page} pageSize={25} total={list.data.total} onPage={setPage} />}
      </Card>
    </div>
  );
}
