import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bot, CheckCheck, Plus, User as UserIcon } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import type { Lookup, Position } from '@/api/types';
import { ProductPicker } from '@/components/ProductPicker';
import { Timeline, type TimelineItem } from '@/components/Timeline';
import { Badge, Button, Card, DataTable, Input, KeyValue, Modal, PageHeader, Pagination, SearchBox, Select, SkeletonRows, StatusBadge, Tabs, Textarea } from '@/components/ui';
import { useCurrentLocation } from '@/hooks/useCurrentLocation';
import { api, type Page } from '@/lib/api';
import { formatDateTime, formatINR, formatNum, titleCase } from '@/lib/format';
import { useToast } from '@/lib/toast';

export interface PR {
  id: number;
  status: string;
  product_id: number;
  product: string;
  sku: string;
  unit: string;
  location: string;
  suggested_qty: number;
  final_qty: number | null;
  suggested_supplier_id: number | null;
  supplier: string | null;
  est_unit_price: number;
  est_total: number;
  reason_text: string | null;
  created_by: string;
  created_at: string;
  required_levels: number;
  rejection_reason: string | null;
  po_id: number | null;
  current_level: number | null;
  current_role: string | null;
  escalated: boolean;
  approvals: { level: number; role: string; decision: string; via: string | null; comment: string | null; decided_at: string | null }[];
}
interface PRDetail extends PR {
  reason_json: Record<string, unknown> | null;
  position: Position;
  pack_size: number;
  history: TimelineItem[];
  supplier_options: { supplier_id: number; name: string; unit_price: number; lead_time_days: number; score: number | null }[];
}

/** The "why" behind an AI suggestion: every input of the reorder calculation (spec 7.3). */
export function ExplanationPanel({ pr }: { pr: PRDetail }) {
  const { t } = useTranslation();
  const r = pr.reason_json ?? {};
  const scalar = Object.entries(r).filter(([, v]) => typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean');
  const supplier = r.supplier as { breakdown?: Record<string, number>; name?: string } | undefined;
  return (
    <div className="space-y-3 rounded-lg border border-violet-200 bg-violet-50/60 p-3 dark:border-violet-900 dark:bg-violet-950/30">
      <p className="flex items-center gap-1.5 text-sm font-semibold text-violet-800 dark:text-violet-300">
        <Bot className="h-4 w-4" /> {t('approvals.whyTitle')}
      </p>
      {pr.reason_text && <p className="text-sm text-slate-700 dark:text-slate-200">{pr.reason_text}</p>}
      {scalar.length > 0 && (
        <KeyValue items={scalar.map(([k, v]) => [titleCase(k), typeof v === 'number' ? formatNum(v) : String(v)])} />
      )}
      {supplier?.breakdown && (
        <div>
          <p className="mb-1 text-xs font-medium text-slate-500">{t('approvals.supplierWhy', { name: supplier.name ?? '' })}</p>
          <div className="space-y-1">
            {Object.entries(supplier.breakdown).map(([k, v]) => (
              <div key={k} className="flex items-center gap-2 text-xs">
                <span className="w-20 shrink-0 text-slate-500">{titleCase(k)}</span>
                <div className="h-2 flex-1 rounded bg-slate-200 dark:bg-slate-800">
                  <div className="h-2 rounded bg-violet-500" style={{ width: `${Math.min(100, Math.max(0, v))}%` }} />
                </div>
                <span className="w-10 text-right tabular-nums">{v.toFixed(0)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Decision({ id, onDone }: { id: number; onDone: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['pr', id], queryFn: () => api.get<PRDetail>(`/purchase-requests/${id}`) });
  const [qty, setQty] = useState('');
  const [supplier, setSupplier] = useState('');
  const [comment, setComment] = useState('');
  useEffect(() => {
    if (q.data) {
      setQty(String(q.data.final_qty ?? q.data.suggested_qty));
      setSupplier(String(q.data.suggested_supplier_id ?? ''));
    }
  }, [q.data]);
  const submit = useMutation({
    mutationFn: () => api.post<PR>(`/purchase-requests/${id}/submit`),
    onSuccess: (r) => {
      toast.success(t('approvals.decided', { status: t(`status.${r.status.toLowerCase()}`) }));
      void qc.invalidateQueries({ queryKey: ['prs'] });
      void qc.invalidateQueries({ queryKey: ['pr', id] });
    },
    onError: (e) => toast.error(e),
  });
  const decide = useMutation({
    mutationFn: (action: 'approve' | 'reject') =>
      api.post<PR>(`/purchase-requests/${id}/decide`, {
        action,
        comment: comment || null,
        final_qty: action === 'approve' ? Number(qty) : null,
        final_supplier_id: action === 'approve' && supplier ? Number(supplier) : null,
      }),
    onSuccess: (pr) => {
      toast.success(t('approvals.decided', { status: t(`status.${pr.status.toLowerCase()}`) }));
      void qc.invalidateQueries({ queryKey: ['prs'] });
      void qc.invalidateQueries({ queryKey: ['notifications'] });
      onDone();
    },
    onError: (e) => toast.error(e),
  });
  if (!q.data) return <SkeletonRows rows={6} />;
  const pr = q.data;
  const pending = pr.status === 'PENDING_APPROVAL';
  const price = pr.supplier_options.find((s) => String(s.supplier_id) === supplier)?.unit_price ?? pr.est_unit_price;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={pr.status} />
        <Badge tone={pr.created_by === 'agent' ? 'purple' : 'gray'}>{pr.created_by === 'agent' ? t('approvals.byAgent') : t('approvals.byUser')}</Badge>
        {pr.current_role && <Badge tone="amber">{t('approvals.level', { level: pr.current_level, role: t(`roles.${pr.current_role}`) })}</Badge>}
        {pr.escalated && <Badge tone="red">{t('approvals.escalated')}</Badge>}
        {pr.po_id && <Link className="text-sm text-brand-700 hover:underline dark:text-brand-400" to={`/orders/${pr.po_id}`}>{t('approvals.viewPo')}</Link>}
      </div>
      <KeyValue items={[
        [t('common.product'), `${pr.product} (${pr.sku})`],
        [t('products.onHand'), `${formatNum(pr.position.on_hand)} ${pr.unit}`],
        [t('products.onOrder'), formatNum(pr.position.on_order)],
        [t('approvals.suggested'), `${formatNum(pr.suggested_qty)} ${pr.unit}`],
        [t('approvals.estTotal'), formatINR(pr.est_total)],
        [t('stock.location'), pr.location],
      ]} />
      <ExplanationPanel pr={pr} />
      {pending && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label={`${t('approvals.finalQty')} (${t('products.pack')} ${formatNum(pr.pack_size)})`} type="number" value={qty} onChange={(e) => setQty(e.target.value)} />
          <Select label={t('nav.suppliers')} value={supplier} onChange={(e) => setSupplier(e.target.value)}
            options={pr.supplier_options.map((s) => ({ value: s.supplier_id, label: `${s.name} · ${formatINR(s.unit_price)} · ${s.lead_time_days}d${s.score !== null ? ` · ${s.score}` : ''}` }))} />
          <p className="text-sm text-slate-600 dark:text-slate-300 sm:col-span-2">{t('approvals.newTotal')}: <b>{formatINR(Number(qty) * price)}</b></p>
          <Textarea className="sm:col-span-2" label={t('approvals.comment')} value={comment} onChange={(e) => setComment(e.target.value)} />
          <div className="flex gap-2 sm:col-span-2">
            <Button variant="success" loading={decide.isPending} disabled={!(Number(qty) > 0)} onClick={() => decide.mutate('approve')}>{t('approvals.approve')}</Button>
            <Button variant="danger" loading={decide.isPending} disabled={comment.trim().length < 3} onClick={() => decide.mutate('reject')}
              title={t('approvals.rejectHint')}>{t('approvals.reject')}</Button>
          </div>
        </div>
      )}
      {pr.status === 'DRAFT' && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800">
          <span className="flex-1">{t('approvals.draftHint')}</span>
          <Button loading={submit.isPending} onClick={() => submit.mutate()}>{t('approvals.submit')}</Button>
        </div>
      )}
      {pr.rejection_reason && <p className="rounded-md bg-rose-50 p-2 text-sm text-rose-700 dark:bg-rose-900/30 dark:text-rose-300">{pr.rejection_reason}</p>}
      <div>
        <p className="mb-2 text-sm font-semibold">{t('approvals.history')}</p>
        <Timeline items={pr.history} />
        <ul className="mt-2 space-y-1 text-xs text-slate-500">
          {pr.approvals.map((a) => (
            <li key={a.level}>L{a.level} · {t(`roles.${a.role}`, { defaultValue: a.role })} · {a.decision}{a.via ? ` (${t(`via.${a.via}`, { defaultValue: a.via })})` : ''}{a.decided_at ? ` · ${formatDateTime(a.decided_at)}` : ''}{a.comment ? ` · ${a.comment}` : ''}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function NewRequest({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const [locationId] = useCurrentLocation();
  const [picked, setPicked] = useState<Lookup | null>(null);
  const [qty, setQty] = useState('');
  const [note, setNote] = useState('');
  const save = useMutation({
    mutationFn: () => api.post<PR>('/purchase-requests', { product_id: picked!.product.id, location_id: locationId, qty: Number(qty), note: note || null }),
    onSuccess: (pr) => {
      toast.success(t('approvals.created', { id: pr.id, status: t(`status.${pr.status.toLowerCase()}`) }));
      void qc.invalidateQueries({ queryKey: ['prs'] });
      setPicked(null);
      setQty('');
      onClose();
    },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal open={open} onClose={onClose} title={t('approvals.new')}
      footer={<Button loading={save.isPending} disabled={!picked || !(Number(qty) > 0)} onClick={() => save.mutate()}>{t('common.submit')}</Button>}>
      <div className="space-y-3">
        <ProductPicker onPick={setPicked} locationId={locationId} />
        {picked && <p className="text-sm">{picked.product.name} · {t('products.onHand')} {formatNum(picked.stock.on_hand)}</p>}
        <Input label={t('common.qty')} type="number" value={qty} onChange={(e) => setQty(e.target.value)} />
        <Textarea label={t('common.notes')} value={note} onChange={(e) => setNote(e.target.value)} />
        <p className="text-xs text-slate-500">{t('approvals.newHint')}</p>
      </div>
    </Modal>
  );
}

type Tab = 'mine' | 'pending' | 'all';

export default function Approvals() {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const [sp, setSp] = useSearchParams();
  const [tab, setTab] = useState<Tab>('mine');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string | number>>(new Set());
  const [creating, setCreating] = useState(false);
  const openId = sp.get('pr') ? Number(sp.get('pr')) : null;
  const params = tab === 'mine' ? { mine: true } : tab === 'pending' ? { status: 'PENDING_APPROVAL' } : {};
  const list = useQuery({
    queryKey: ['prs', tab, q, page],
    queryFn: () => api.get<Page<PR>>('/purchase-requests', { ...params, q, page, page_size: 25 }),
  });
  const bulk = useMutation({
    mutationFn: () => api.post<{ approved: number[]; failed: { id: number; error: string }[]; purchase_orders: string[] }>('/purchase-requests/bulk-approve', { ids: [...selected] }),
    onSuccess: (r) => {
      toast.success(t('approvals.bulkDone', { n: r.approved.length, pos: r.purchase_orders.join(', ') || '—' }));
      r.failed.forEach((f) => toast.error(`#${f.id}: ${f.error}`));
      setSelected(new Set());
      void qc.invalidateQueries({ queryKey: ['prs'] });
    },
    onError: (e) => toast.error(e),
  });
  return (
    <div>
      <PageHeader title={t('nav.approvals')} subtitle={t('approvals.subtitle')}
        actions={<Button variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>{t('approvals.new')}</Button>} />
      <Tabs<Tab> value={tab} onChange={(v) => { setTab(v); setPage(1); setSelected(new Set()); }}
        tabs={[{ value: 'mine', label: t('approvals.mine') }, { value: 'pending', label: t('approvals.allPending') }, { value: 'all', label: t('approvals.allRequests') }]} />
      <Card title={<SearchBox value={q} onChange={(v) => { setQ(v); setPage(1); }} />}
        actions={tab !== 'all' && <Button variant="success" icon={<CheckCheck className="h-4 w-4" />} disabled={!selected.size} loading={bulk.isPending} onClick={() => bulk.mutate()}>{t('approvals.bulk', { n: selected.size })}</Button>}>
        <DataTable<PR>
          rows={list.data?.items}
          loading={list.isLoading}
          error={list.error}
          onRetry={() => list.refetch()}
          rowKey={(r) => r.id}
          selectable={tab !== 'all'}
          selected={selected}
          onSelect={setSelected}
          onRowClick={(r) => setSp({ pr: String(r.id) })}
          empty={tab === 'mine' ? t('approvals.nothingMine') : t('common.noData')}
          columns={[
            { key: 'id', header: '#', render: (r) => <span className="flex items-center gap-1">{r.created_by === 'agent' ? <Bot className="h-3.5 w-3.5 text-violet-600" /> : <UserIcon className="h-3.5 w-3.5 text-slate-400" />}{r.id}</span> },
            { key: 'product', header: t('common.product'), render: (r) => <div className="max-w-xs whitespace-normal"><p className="font-medium">{r.product}</p><p className="line-clamp-1 text-xs text-slate-500">{r.reason_text}</p></div> },
            { key: 'qty', header: t('common.qty'), align: 'right', render: (r) => `${formatNum(r.final_qty ?? r.suggested_qty)} ${r.unit}` },
            { key: 'supplier', header: t('common.supplier') },
            { key: 'est_total', header: t('approvals.estTotal'), align: 'right', render: (r) => formatINR(r.est_total) },
            { key: 'created_at', header: t('common.date'), render: (r) => formatDateTime(r.created_at) },
            { key: 'status', header: t('common.status'), render: (r) => <span className="flex flex-col items-start gap-0.5"><StatusBadge status={r.status} />{r.current_role && <span className="text-[11px] text-slate-500">L{r.current_level} {t(`roles.${r.current_role}`)}{r.escalated ? ' ⚠' : ''}</span>}</span> },
          ]}
        />
        {list.data && <Pagination page={page} pageSize={25} total={list.data.total} onPage={setPage} />}
      </Card>
      <Modal open={!!openId} onClose={() => setSp({})} title={openId ? `${t('approvals.request')} #${openId}` : ''} wide>
        {openId && <Decision id={openId} onDone={() => setSp({})} />}
      </Modal>
      <NewRequest open={creating} onClose={() => setCreating(false)} />
    </div>
  );
}
