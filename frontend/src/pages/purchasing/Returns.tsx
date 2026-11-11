import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FileDown, Plus } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import type { Batch, Lookup } from '@/api/types';
import { ProductPicker } from '@/components/ProductPicker';
import { Timeline, type TimelineItem } from '@/components/Timeline';
import { Button, Card, DataTable, Input, KeyValue, Modal, PageHeader, Pagination, Select, StatusBadge, Textarea } from '@/components/ui';
import { useCurrentLocation } from '@/hooks/useCurrentLocation';
import { useSupplierOptions } from '@/hooks/useMasters';
import { api, type Page } from '@/lib/api';
import { formatDate, formatDateTime, formatINR, formatNum } from '@/lib/format';
import { useToast } from '@/lib/toast';

interface Ret {
  id: number;
  return_no: string;
  status: string;
  supplier: string;
  supplier_id: number;
  reason: string | null;
  total: number;
  tax: number;
  debit_note_no: string | null;
  credit_note_ref: string | null;
  created_at: string;
  lines: { id: number; product: string; qty: number; unit_price: number; reason: string | null }[];
  history?: TimelineItem[];
}

export function NewReturn({ open, onClose, preset }: { open: boolean; onClose: () => void; preset?: { batch: Batch; supplierId?: number } }) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const suppliers = useSupplierOptions();
  const [locationId] = useCurrentLocation();
  const [supplier, setSupplier] = useState(preset?.supplierId ? String(preset.supplierId) : '');
  const [reason, setReason] = useState(preset ? 'Expired / near expiry stock' : '');
  const [lines, setLines] = useState<{ batch: Batch; qty: string }[]>(preset ? [{ batch: preset.batch, qty: String(preset.batch.qty_on_hand) }] : []);
  const [picked, setPicked] = useState<Lookup | null>(null);
  const batches = useQuery({
    queryKey: ['stock', 'batches', 'return', picked?.product.id, locationId],
    queryFn: () => api.get<Page<Batch>>('/stock/batches', { product_id: picked!.product.id, location_id: locationId, page_size: 50 }),
    enabled: !!picked,
  });
  const save = useMutation({
    mutationFn: () => api.post<Ret>('/returns', {
      supplier_id: Number(supplier), location_id: preset?.batch.location_id ?? locationId, reason,
      lines: lines.map((l) => ({ batch_id: l.batch.id, qty: Number(l.qty) })),
    }),
    onSuccess: (r) => { toast.success(t('returns.created', { no: r.return_no })); void qc.invalidateQueries({ queryKey: ['returns'] }); onClose(); },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal open={open} onClose={onClose} wide title={t('returns.new')}
      footer={<Button loading={save.isPending} disabled={!supplier || reason.trim().length < 3 || !lines.length} onClick={() => save.mutate()}>{t('returns.submit')}</Button>}>
      <div className="space-y-3">
        <Select label={t('nav.suppliers')} value={supplier} onChange={(e) => setSupplier(e.target.value)} placeholder="—"
          options={(suppliers.data ?? []).map((s) => ({ value: s.id, label: s.name }))} />
        {!preset && <ProductPicker onPick={setPicked} locationId={locationId} />}
        {picked && (batches.data?.items ?? []).map((b) => (
          <button key={b.id} type="button" className="flex w-full justify-between rounded border border-slate-200 px-3 py-1.5 text-left text-sm dark:border-slate-700"
            onClick={() => setLines((ls) => ls.some((x) => x.batch.id === b.id) ? ls : [...ls, { batch: b, qty: String(b.qty_on_hand) }])}>
            <span>{b.batch_no} · {formatDate(b.expiry_date)}</span><b>{formatNum(b.qty_on_hand)}</b>
          </button>
        ))}
        {lines.map((l, i) => (
          <div key={l.batch.id} className="flex items-end gap-2">
            <p className="flex-1 text-sm">{l.batch.product_name} · {l.batch.batch_no}</p>
            <Input className="w-28" label={t('common.qty')} type="number" value={l.qty} onChange={(e) => setLines((ls) => ls.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} />
          </div>
        ))}
        <Textarea label={t('common.reason')} value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
    </Modal>
  );
}

export default function Returns() {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const [sp, setSp] = useSearchParams();
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [text, setText] = useState('');
  const openId = sp.get('id');
  const list = useQuery({ queryKey: ['returns', page], queryFn: () => api.get<Page<Ret>>('/returns', { page, page_size: 25 }) });
  const detail = useQuery({ queryKey: ['returns', 'detail', openId], queryFn: () => api.get<Ret>(`/returns/${openId}`), enabled: !!openId });
  const act = useMutation({
    mutationFn: (action: string) => api.post<Ret>(`/returns/${openId}/${action}`, { text: text || null }),
    onSuccess: (r) => { qc.setQueryData(['returns', 'detail', openId], r); setText(''); void qc.invalidateQueries({ queryKey: ['returns'] }); toast.success(t('common.saved')); },
    onError: (e) => toast.error(e),
  });
  const r = detail.data;
  const actions: Record<string, string[]> = { DRAFT: ['submit', 'cancel'], PENDING_APPROVAL: ['approve', 'reject'], APPROVED: ['dispatch', 'cancel'], DISPATCHED: ['credit'] };
  return (
    <div>
      <PageHeader title={t('nav.returns')} subtitle={t('returns.subtitle')} actions={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>{t('returns.new')}</Button>} />
      <Card>
        <DataTable<Ret> rows={list.data?.items} loading={list.isLoading} error={list.error} rowKey={(x) => x.id} onRowClick={(x) => setSp({ id: String(x.id) })}
          empty={t('returns.empty')}
          columns={[
            { key: 'return_no', header: '#', className: 'font-mono text-xs' },
            { key: 'supplier', header: t('common.supplier') },
            { key: 'reason', header: t('common.reason'), render: (x) => <span className="line-clamp-1 whitespace-normal text-xs">{x.reason}</span> },
            { key: 'total', header: t('common.total'), align: 'right', render: (x) => formatINR(x.total) },
            { key: 'created_at', header: t('common.date'), render: (x) => formatDateTime(x.created_at) },
            { key: 'status', header: t('common.status'), render: (x) => <StatusBadge status={x.status} /> },
          ]} />
        {list.data && <Pagination page={page} pageSize={25} total={list.data.total} onPage={setPage} />}
      </Card>
      <Modal open={!!openId} onClose={() => setSp({})} wide title={r?.return_no ?? ''}
        footer={r && <>
          {r.debit_note_no && <Button variant="secondary" icon={<FileDown className="h-4 w-4" />} onClick={() => api.open(`/returns/${r.id}/pdf`).catch(toast.error)}>{t('returns.debitNote')}</Button>}
          {(actions[r.status] ?? []).map((a) => (
            <Button key={a} variant={['reject', 'cancel'].includes(a) ? 'danger' : 'primary'} loading={act.isPending}
              disabled={a === 'credit' && !text.trim()} onClick={() => act.mutate(a)}>{t(`returns.${a}`)}</Button>
          ))}
        </>}>
        {r && (
          <div className="space-y-3 text-sm">
            <KeyValue items={[[t('common.supplier'), r.supplier], [t('common.status'), <StatusBadge key="s" status={r.status} />], [t('returns.debitNote'), r.debit_note_no ?? '—'], [t('returns.creditNote'), r.credit_note_ref ?? '—'], [t('common.total'), formatINR(r.total)]]} />
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">{r.lines.map((l) => <li key={l.id} className="flex justify-between py-1"><span>{l.product}</span><span>{formatNum(l.qty)} × {formatINR(l.unit_price)}</span></li>)}</ul>
            {(r.status === 'DISPATCHED' || ['PENDING_APPROVAL', 'DRAFT', 'APPROVED'].includes(r.status)) && (
              <Input label={r.status === 'DISPATCHED' ? t('returns.creditNote') : t('common.notes')} value={text} onChange={(e) => setText(e.target.value)} />
            )}
            {r.history && <Timeline items={r.history} />}
          </div>
        )}
      </Modal>
      <NewReturn open={creating} onClose={() => setCreating(false)} />
    </div>
  );
}
