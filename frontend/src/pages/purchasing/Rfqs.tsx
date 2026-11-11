import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Mail, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import type { Lookup } from '@/api/types';
import { ProductPicker } from '@/components/ProductPicker';
import { Badge, Button, Card, Checkbox, DataTable, EmptyState, ErrorState, Input, Modal, PageHeader, Pagination, SkeletonRows, StatusBadge, Textarea } from '@/components/ui';
import { usePublicSettings, useSupplierOptions } from '@/hooks/useMasters';
import { api, type Page } from '@/lib/api';
import { formatDate, formatDateTime, formatINR, formatNum } from '@/lib/format';
import { useToast } from '@/lib/toast';

interface RfqRow {
  id: number;
  rfq_no: string;
  title: string;
  status: string;
  due_date: string | null;
  created_at: string;
  items: { id: number; product: string; qty: number; unit: string }[];
  suppliers: { supplier_id: number; name: string; responded_at: string | null }[];
}
interface Quote {
  id: number;
  supplier: string;
  unit_price: number;
  lead_time_days: number | null;
  min_order_qty: number | null;
  valid_till: string | null;
  status: string;
  total: number;
  saving_pct: number | null;
  note: string | null;
}
interface RfqDetail extends RfqRow {
  comparison: { item_id: number; product: string; qty: number; unit: string; current_best_price: number | null; quotes: Quote[] }[];
}

function NewRfq({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const sups = useSupplierOptions();
  const [title, setTitle] = useState('');
  const [due, setDue] = useState('');
  const [note, setNote] = useState('');
  const [items, setItems] = useState<{ l: Lookup; qty: string }[]>([]);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const save = useMutation({
    mutationFn: () => api.post<RfqRow>('/rfqs', { title, due_date: due || null, note: note || null, supplier_ids: [...chosen],
      items: items.map((i) => ({ product_id: i.l.product.id, qty: Number(i.qty) })) }),
    onSuccess: (r) => { toast.success(t('rfq.sent', { no: r.rfq_no })); void qc.invalidateQueries({ queryKey: ['rfqs'] }); onClose(); navigate(`/rfqs/${r.id}`); },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal open={open} onClose={onClose} wide title={t('rfq.new')}
      footer={<Button icon={<Mail className="h-4 w-4" />} loading={save.isPending} disabled={title.trim().length < 3 || !items.length || !chosen.size || items.some((i) => !(Number(i.qty) > 0))}
        onClick={() => save.mutate()}>{t('rfq.send')}</Button>}>
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label={t('rfq.title')} value={title} onChange={(e) => setTitle(e.target.value)} />
          <Input label={t('rfq.due')} type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        </div>
        <ProductPicker onPick={(l) => setItems((xs) => (xs.some((x) => x.l.product.id === l.product.id) ? xs : [...xs, { l, qty: '' }]))} />
        {items.map((it, i) => (
          <div key={it.l.product.id} className="flex items-end gap-2">
            <p className="flex-1 truncate text-sm">{it.l.product.name}</p>
            <Input className="w-28" label={t('common.qty')} type="number" value={it.qty} onChange={(e) => setItems((xs) => xs.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} />
            <Button variant="ghost" aria-label={t('common.remove')} onClick={() => setItems((xs) => xs.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4 text-rose-600" /></Button>
          </div>
        ))}
        <div>
          <p className="label">{t('rfq.suppliers')}</p>
          <div className="grid gap-1 sm:grid-cols-2">
            {(sups.data ?? []).map((s) => (
              <Checkbox key={s.id} label={s.name} checked={chosen.has(s.id)} onChange={(v) => setChosen((c) => { const n = new Set(c); if (v) n.add(s.id); else n.delete(s.id); return n; })} />
            ))}
          </div>
        </div>
        <Textarea label={t('common.notes')} value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
    </Modal>
  );
}

function EmailQuotes() {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const settings = usePublicSettings();
  const enabled = !!settings.data?.features.imap;
  const q = useQuery({
    queryKey: ['email-quotes'],
    queryFn: () => api.get<{ enabled: boolean; items: { id: number; supplier: string; product: string; unit_price: number; note: string | null }[] }>('/quotes/pending'),
    enabled,
  });
  const act = useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'use' | 'reject' }) => api.post(`/quotes/${id}/${action}`),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['email-quotes'] }); toast.success(t('common.saved')); },
    onError: (e) => toast.error(e),
  });
  const fetchNow = useMutation({
    mutationFn: () => api.post<{ emails: number; quotes: number }>('/quotes/fetch-email'),
    onSuccess: (r) => { toast.success(t('rfq.fetched', { emails: r.emails, quotes: r.quotes })); void qc.invalidateQueries({ queryKey: ['email-quotes'] }); },
    onError: (e) => toast.error(e),
  });
  if (!enabled) return null; // hidden without IMAP configuration (spec 6.7)
  return (
    <Card title={t('rfq.emailQuotes')} actions={<Button size="sm" variant="secondary" loading={fetchNow.isPending} onClick={() => fetchNow.mutate()}>{t('rfq.checkInbox')}</Button>}>
      <DataTable rows={q.data?.items} loading={q.isLoading} rowKey={(r) => r.id} empty={t('rfq.noEmailQuotes')}
        columns={[
          { key: 'supplier', header: t('common.supplier') },
          { key: 'product', header: t('common.product') },
          { key: 'unit_price', header: t('suppliers.unitPrice'), align: 'right', render: (r) => formatINR(r.unit_price) },
          { key: 'note', header: t('rfq.source'), render: (r) => <span className="whitespace-normal text-xs">{r.note}</span> },
          { key: 'a', header: '', render: (r) => <div className="flex gap-1"><Button size="sm" onClick={() => act.mutate({ id: r.id, action: 'use' })}>{t('rfq.use')}</Button><Button size="sm" variant="ghost" onClick={() => act.mutate({ id: r.id, action: 'reject' })}>{t('approvals.reject')}</Button></div> },
        ]} />
    </Card>
  );
}

export function RfqList() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const q = useQuery({ queryKey: ['rfqs', page], queryFn: () => api.get<Page<RfqRow>>('/rfqs', { page, page_size: 25 }) });
  return (
    <div className="space-y-4">
      <PageHeader title={t('nav.rfqs')} subtitle={t('rfq.subtitle')} actions={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>{t('rfq.new')}</Button>} />
      <Card>
        <DataTable<RfqRow> rows={q.data?.items} loading={q.isLoading} error={q.error} rowKey={(r) => r.id} onRowClick={(r) => navigate(`/rfqs/${r.id}`)} empty={t('rfq.empty')}
          columns={[
            { key: 'rfq_no', header: '#', className: 'font-mono text-xs' },
            { key: 'title', header: t('rfq.title') },
            { key: 'items', header: t('nav.products'), align: 'right', render: (r) => r.items.length },
            { key: 'responses', header: t('rfq.responses'), align: 'right', render: (r) => `${r.suppliers.filter((s) => s.responded_at).length}/${r.suppliers.length}` },
            { key: 'due_date', header: t('rfq.due'), render: (r) => formatDate(r.due_date) },
            { key: 'status', header: t('common.status'), render: (r) => <StatusBadge status={r.status} /> },
          ]} />
        {q.data && <Pagination page={page} pageSize={25} total={q.data.total} onPage={setPage} />}
      </Card>
      <EmailQuotes />
      <NewRfq open={creating} onClose={() => setCreating(false)} />
    </div>
  );
}

export function RfqDetailPage() {
  const { id } = useParams();
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['rfqs', 'detail', id], queryFn: () => api.get<RfqDetail>(`/rfqs/${id}`) });
  const use = useMutation({
    mutationFn: (quoteId: number) => api.post(`/quotes/${quoteId}/use`),
    onSuccess: () => { toast.success(t('rfq.used')); void qc.invalidateQueries({ queryKey: ['rfqs'] }); },
    onError: (e) => toast.error(e),
  });
  const close = useMutation({ mutationFn: () => api.post<RfqDetail>(`/rfqs/${id}/close`), onSuccess: (d) => qc.setQueryData(['rfqs', 'detail', id], d), onError: (e) => toast.error(e) });
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <SkeletonRows rows={6} />;
  const r = q.data;
  return (
    <div className="space-y-4">
      <Link to="/rfqs" className="inline-flex items-center gap-1 text-sm text-slate-500"><ArrowLeft className="h-4 w-4" />{t('nav.rfqs')}</Link>
      <PageHeader title={`${r.rfq_no} · ${r.title}`} subtitle={`${t('rfq.due')} ${formatDate(r.due_date)} · ${formatDateTime(r.created_at)}`}
        actions={<><StatusBadge status={r.status} />{r.status === 'OPEN' && <Button variant="secondary" loading={close.isPending} onClick={() => close.mutate()}>{t('rfq.closeQuotes')}</Button>}</>} />
      <Card title={t('rfq.invited')}>
        <div className="flex flex-wrap gap-2">{r.suppliers.map((s) => <Badge key={s.supplier_id} tone={s.responded_at ? 'green' : 'gray'}>{s.name}{s.responded_at ? ' ✓' : ''}</Badge>)}</div>
      </Card>
      {r.comparison.map((c) => (
        <Card key={c.item_id} title={`${c.product} — ${formatNum(c.qty)} ${c.unit}`} actions={<span className="text-xs text-slate-500">{t('rfq.currentBest')}: {formatINR(c.current_best_price)}</span>}>
          {c.quotes.length === 0 ? <EmptyState title={t('rfq.noQuotes')} /> : (
            <DataTable<Quote> rows={c.quotes} rowKey={(x) => x.id}
              columns={[
                { key: 'supplier', header: t('common.supplier'), render: (x) => <span className="flex items-center gap-1">{x.supplier}{x.id === c.quotes[0].id && <Badge tone="green">{t('rfq.lowest')}</Badge>}</span> },
                { key: 'unit_price', header: t('suppliers.unitPrice'), align: 'right', render: (x) => formatINR(x.unit_price) },
                { key: 'saving_pct', header: t('rfq.vsCurrent'), align: 'right', render: (x) => (x.saving_pct == null ? '—' : <span className={x.saving_pct > 0 ? 'text-emerald-600' : 'text-rose-600'}>{x.saving_pct > 0 ? '−' : '+'}{Math.abs(x.saving_pct)}%</span>) },
                { key: 'lead_time_days', header: t('suppliers.leadTime'), align: 'right', render: (x) => (x.lead_time_days == null ? '—' : `${x.lead_time_days} d`) },
                { key: 'total', header: t('common.total'), align: 'right', render: (x) => formatINR(x.total) },
                { key: 'status', header: t('common.status'), render: (x) => <StatusBadge status={x.status} /> },
                { key: 'a', header: '', render: (x) => x.status === 'submitted' && <Button size="sm" loading={use.isPending} onClick={() => use.mutate(x.id)}>{t('rfq.use')}</Button> },
              ]} />
          )}
        </Card>
      ))}
    </div>
  );
}
