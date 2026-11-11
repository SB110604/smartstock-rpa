import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, FileDown, Truck } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Timeline } from '@/components/Timeline';
import { Button, Card, DataTable, ErrorState, Input, Modal, PageHeader, Pagination, SkeletonRows, Stat, StatusBadge, Textarea } from '@/components/ui';
import { api, type Page } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { daysFromNow, formatDate, formatINR, isoDate } from '@/lib/format';
import { useToast } from '@/lib/toast';
import { LinesTable, type PODetail } from '@/pages/purchasing/OrderDetail';
import { POTable, type PORow } from '@/pages/purchasing/Orders';

interface Summary {
  open_orders: number;
  awaiting_confirmation: number;
  late: number;
  total_orders: number;
  rfqs_awaiting: number;
  score: { total: number; on_time_pct: number; price: number; lead: number; quality: number } | null;
}
type PortalOrder = PODetail & { actions: string[] };

export function PortalHome() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('open');
  const s = useQuery({ queryKey: ['portal', 'summary'], queryFn: () => api.get<Summary>('/portal/summary') });
  const list = useQuery({ queryKey: ['portal', 'orders', status, page], queryFn: () => api.get<Page<PORow>>('/portal/orders', { status, page, page_size: 20 }) });
  return (
    <div className="space-y-4">
      <PageHeader title={t('portal.welcome', { name: user?.supplier_name ?? '' })} subtitle={t('portal.subtitle')} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label={t('portal.openOrders')} value={s.data?.open_orders ?? '—'} />
        <Stat label={t('portal.toConfirm')} value={s.data?.awaiting_confirmation ?? '—'} tone={s.data?.awaiting_confirmation ? 'amber' : undefined} />
        <Stat label={t('orders.late')} value={s.data?.late ?? '—'} tone={s.data?.late ? 'red' : undefined} />
        <Stat label={t('portal.rfqs')} value={s.data?.rfqs_awaiting ?? '—'} />
        <Stat label={t('suppliers.score')} value={s.data?.score ? s.data.score.total.toFixed(1) : '—'}
          hint={s.data?.score ? `${t('suppliers.onTime')} ${s.data.score.on_time_pct.toFixed(0)}%` : undefined} />
      </div>
      <Card title={t('portal.orders')} actions={
        <div className="flex gap-1">
          {['open', ''].map((v) => <Button key={v} size="sm" variant={status === v ? 'primary' : 'secondary'} onClick={() => { setStatus(v); setPage(1); }}>{v ? t('orders.filter_open') : t('orders.filter_all')}</Button>)}
        </div>}>
        <POTable rows={list.data?.items} loading={list.isLoading} error={list.error} onOpen={(r) => navigate(`/portal/orders/${r.id}`)} />
        {list.data && <Pagination page={page} pageSize={20} total={list.data.total} onPage={setPage} />}
      </Card>
    </div>
  );
}

export function PortalOrder() {
  const { id } = useParams();
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const [mode, setMode] = useState<null | 'confirm' | 'reject' | 'dispatch' | 'invoice'>(null);
  const [f, setF] = useState({ eta: daysFromNow(3), reason: '', tracking: '', courier: '', note: '', invoice_no: '', invoice_date: isoDate() });
  const [file, setFile] = useState<File | null>(null);
  const q = useQuery({ queryKey: ['portal', 'order', id], queryFn: () => api.get<PortalOrder>(`/portal/orders/${id}`) });
  const act = useMutation({
    mutationFn: async () => {
      if (mode === 'confirm') return api.post(`/portal/orders/${id}/confirm`, { eta: f.eta || null, note: f.note || null });
      if (mode === 'reject') return api.post(`/portal/orders/${id}/reject`, { reason: f.reason });
      if (mode === 'dispatch') return api.post(`/portal/orders/${id}/dispatch`, { eta: f.eta, tracking_ref: f.tracking || null, courier_name: f.courier || null, note: f.note || null });
      const fd = new FormData();
      fd.append('invoice_no', f.invoice_no);
      fd.append('invoice_date', f.invoice_date);
      if (file) fd.append('file', file);
      return api.upload(`/portal/orders/${id}/invoice`, fd);
    },
    onSuccess: () => { toast.success(t('common.saved')); setMode(null); void qc.invalidateQueries({ queryKey: ['portal'] }); },
    onError: (e) => toast.error(e),
  });
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <SkeletonRows rows={8} />;
  const po = q.data;
  const valid = mode === 'reject' ? f.reason.trim().length >= 3 : mode === 'invoice' ? !!f.invoice_no.trim() : mode === 'dispatch' ? !!f.eta : true;
  return (
    <div className="space-y-4">
      <Link to="/portal" className="inline-flex items-center gap-1 text-sm text-slate-500"><ArrowLeft className="h-4 w-4" />{t('portal.orders')}</Link>
      <PageHeader title={po.po_no} subtitle={`${t('common.date')} ${formatDate(po.order_date)} · ${t('orders.expected')} ${formatDate(po.expected_date)} · ${po.location}`}
        actions={<>
          <StatusBadge status={po.status} />
          <Button variant="secondary" icon={<FileDown className="h-4 w-4" />} onClick={() => api.open(`/portal/orders/${po.id}/pdf`).catch(toast.error)}>PDF</Button>
          {po.actions.includes('confirm') && <Button variant="success" onClick={() => setMode('confirm')}>{t('portal.confirm')}</Button>}
          {po.actions.includes('dispatch') && <Button icon={<Truck className="h-4 w-4" />} onClick={() => setMode('dispatch')}>{t('portal.dispatch')}</Button>}
          {po.actions.includes('invoice') && <Button variant="secondary" onClick={() => setMode('invoice')}>{t('portal.uploadInvoice')}</Button>}
          {po.actions.includes('reject') && <Button variant="danger" onClick={() => setMode('reject')}>{t('portal.reject')}</Button>}
        </>} />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={t('orders.lines')} className="lg:col-span-2"><LinesTable po={po} /></Card>
        <Card title={t('orders.tracking')}>
          <p className="mb-3 text-sm">{t('orders.eta')}: <b>{formatDate(po.supplier_eta)}</b>{po.tracking_ref ? ` · ${po.tracking_ref}` : ''}</p>
          <Timeline items={po.timeline} />
          {po.invoices.length > 0 && <ul className="mt-3 text-sm">{po.invoices.map((i) => <li key={i.id}>{i.invoice_no} · {formatINR(i.total)} · <StatusBadge status={i.status} /></li>)}</ul>}
        </Card>
      </div>
      <Modal open={!!mode} onClose={() => setMode(null)} title={mode ? t(`portal.${mode === 'invoice' ? 'uploadInvoice' : mode}`) : ''}
        footer={<Button variant={mode === 'reject' ? 'danger' : 'primary'} disabled={!valid} loading={act.isPending} onClick={() => act.mutate()}>{t('common.submit')}</Button>}>
        <div className="space-y-3">
          {(mode === 'confirm' || mode === 'dispatch') && <Input label={t('orders.eta')} type="date" value={f.eta} onChange={(e) => setF({ ...f, eta: e.target.value })} />}
          {mode === 'dispatch' && <>
            <Input label={t('orders.courier')} value={f.courier} onChange={(e) => setF({ ...f, courier: e.target.value })} />
            <Input label={t('portal.tracking')} value={f.tracking} onChange={(e) => setF({ ...f, tracking: e.target.value })} />
          </>}
          {(mode === 'confirm' || mode === 'dispatch') && <Textarea label={t('common.notes')} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />}
          {mode === 'reject' && <Textarea label={t('common.reason')} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />}
          {mode === 'invoice' && <>
            <Input label={t('orders.invoiceNo')} value={f.invoice_no} onChange={(e) => setF({ ...f, invoice_no: e.target.value })} />
            <Input label={t('common.date')} type="date" value={f.invoice_date} onChange={(e) => setF({ ...f, invoice_date: e.target.value })} />
            <div><label className="label" htmlFor="inv-file">{t('portal.invoiceFile')}</label><input id="inv-file" type="file" accept=".pdf,.jpg,.jpeg,.png" className="input" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></div>
            <p className="text-xs text-slate-500">{t('portal.invoiceHint')}</p>
          </>}
        </div>
      </Modal>
    </div>
  );
}

export function PortalInvoices() {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const q = useQuery({ queryKey: ['portal', 'invoices', page], queryFn: () => api.get<Page<{ id: number; invoice_no: string; invoice_date: string; po_id: number; total: number; status: string; source: string }>>('/portal/invoices', { page }) });
  return (
    <div>
      <PageHeader title={t('nav.invoices')} />
      <Card>
        <DataTable rows={q.data?.items} loading={q.isLoading} error={q.error} rowKey={(r) => r.id}
          columns={[
            { key: 'invoice_no', header: t('orders.invoiceNo'), render: (r) => <Link className="text-brand-700 hover:underline dark:text-brand-400" to={`/portal/orders/${r.po_id}`}>{r.invoice_no}</Link> },
            { key: 'invoice_date', header: t('common.date'), render: (r) => formatDate(r.invoice_date) },
            { key: 'total', header: t('common.total'), align: 'right', render: (r) => formatINR(r.total) },
            { key: 'status', header: t('common.status'), render: (r) => <StatusBadge status={r.status} /> },
          ]} />
        {q.data && <Pagination page={page} pageSize={25} total={q.data.total} onPage={setPage} />}
      </Card>
    </div>
  );
}

interface PortalRfq {
  id: number;
  rfq_no: string;
  title: string;
  status: string;
  due_date: string | null;
  note: string | null;
  responded_at: string | null;
  items: { id: number; product: string; qty: number; unit: string; my_quote: { unit_price: number; lead_time_days: number | null; status: string } | null }[];
}

export function PortalRfqs() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ['portal', 'rfqs'], queryFn: () => api.get<PortalRfq[]>('/portal/rfqs') });
  return (
    <div>
      <PageHeader title={t('portal.rfqsTitle')} subtitle={t('portal.rfqsSubtitle')} />
      <Card>
        <DataTable<PortalRfq> rows={q.data} loading={q.isLoading} error={q.error} rowKey={(r) => r.id} onRowClick={(r) => navigate(`/portal/rfqs/${r.id}`)} empty={t('rfq.empty')}
          columns={[
            { key: 'rfq_no', header: '#', className: 'font-mono text-xs' },
            { key: 'title', header: t('rfq.title') },
            { key: 'due_date', header: t('rfq.due'), render: (r) => formatDate(r.due_date) },
            { key: 'responded_at', header: t('portal.quoted'), render: (r) => (r.responded_at ? formatDate(r.responded_at) : '—') },
            { key: 'status', header: t('common.status'), render: (r) => <StatusBadge status={r.status} /> },
          ]} />
      </Card>
    </div>
  );
}

export function PortalRfqDetail() {
  const { id } = useParams();
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['portal', 'rfq', id], queryFn: () => api.get<PortalRfq>(`/portal/rfqs/${id}`) });
  const [rows, setRows] = useState<Record<number, { price: string; lead: string }>>({});
  const val = (itemId: number, k: 'price' | 'lead', fallback: string) => rows[itemId]?.[k] ?? fallback;
  const save = useMutation({
    mutationFn: () => api.post<PortalRfq>(`/portal/rfqs/${id}/quotes`, {
      quotes: (q.data?.items ?? []).map((i) => ({
        rfq_item_id: i.id,
        unit_price: Number(val(i.id, 'price', String(i.my_quote?.unit_price ?? ''))),
        lead_time_days: Number(val(i.id, 'lead', String(i.my_quote?.lead_time_days ?? ''))) || null,
      })).filter((x) => x.unit_price > 0),
    }),
    onSuccess: (d) => { qc.setQueryData(['portal', 'rfq', id], d); toast.success(t('portal.quoteSent')); },
    onError: (e) => toast.error(e),
  });
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <SkeletonRows rows={5} />;
  const r = q.data;
  const open = r.status === 'OPEN';
  return (
    <div className="space-y-4">
      <Link to="/portal/rfqs" className="inline-flex items-center gap-1 text-sm text-slate-500"><ArrowLeft className="h-4 w-4" />{t('portal.rfqsTitle')}</Link>
      <PageHeader title={`${r.rfq_no} · ${r.title}`} subtitle={`${t('rfq.due')} ${formatDate(r.due_date)}`} actions={<StatusBadge status={r.status} />} />
      {r.note && <p className="text-sm text-slate-600 dark:text-slate-300">{r.note}</p>}
      <Card title={t('portal.yourQuote')} actions={open && <Button loading={save.isPending} onClick={() => save.mutate()}>{t('portal.submitQuote')}</Button>}>
        <div className="space-y-2">
          {r.items.map((i) => (
            <div key={i.id} className="grid grid-cols-[1fr_7rem_6rem] items-end gap-2">
              <p className="text-sm">{i.product} <span className="text-xs text-slate-500">· {i.qty} {i.unit}</span>
                {i.my_quote && <StatusBadge status={i.my_quote.status} />}</p>
              <Input label={t('suppliers.unitPrice')} type="number" step="0.01" disabled={!open} value={val(i.id, 'price', String(i.my_quote?.unit_price ?? ''))}
                onChange={(e) => setRows((x) => ({ ...x, [i.id]: { price: e.target.value, lead: val(i.id, 'lead', String(i.my_quote?.lead_time_days ?? '')) } }))} />
              <Input label={t('suppliers.leadTime')} type="number" disabled={!open} value={val(i.id, 'lead', String(i.my_quote?.lead_time_days ?? ''))}
                onChange={(e) => setRows((x) => ({ ...x, [i.id]: { lead: e.target.value, price: val(i.id, 'price', String(i.my_quote?.unit_price ?? '')) } }))} />
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
