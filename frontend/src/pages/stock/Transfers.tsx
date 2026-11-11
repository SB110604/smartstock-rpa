import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { Lookup } from '@/api/types';
import { ProductPicker } from '@/components/ProductPicker';
import { Button, Card, DataTable, Input, Modal, Pagination, Select, StatusBadge } from '@/components/ui';
import { useLocations } from '@/hooks/useMasters';
import { api, type Page } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { formatDateTime, formatNum } from '@/lib/format';
import { useToast } from '@/lib/toast';

interface Transfer {
  id: number;
  transfer_no: string;
  status: string;
  note: string | null;
  from_location: string;
  to_location: string;
  created_at: string;
  lines: { id: number; product: string; sku: string; batch_id: number | null; qty: number }[];
  history?: { from: string | null; to: string; note: string | null; at: string }[];
}

function NewTransfer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const locs = useLocations();
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [note, setNote] = useState('');
  const [lines, setLines] = useState<{ l: Lookup; qty: string }[]>([]);
  const save = useMutation({
    mutationFn: () =>
      api.post('/transfers', {
        from_location_id: Number(from),
        to_location_id: Number(to),
        note: note || null,
        lines: lines.map((x) => ({ product_id: x.l.product.id, qty: Number(x.qty) })),
      }),
    onSuccess: () => {
      toast.success(t('transfers.created'));
      setLines([]);
      setNote('');
      void qc.invalidateQueries({ queryKey: ['transfers'] });
      onClose();
    },
    onError: (e) => toast.error(e),
  });
  const opts = (locs.data ?? []).map((l) => ({ value: l.id, label: l.name }));
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('transfers.new')}
      wide
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            loading={save.isPending}
            disabled={!from || !to || from === to || !lines.length || lines.some((x) => !(Number(x.qty) > 0))}
            onClick={() => save.mutate()}
          >
            {t('common.submit')}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Select
            label={t('common.from')}
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            placeholder="—"
            options={opts}
          />
          <Select
            label={t('common.to')}
            value={to}
            onChange={(e) => setTo(e.target.value)}
            placeholder="—"
            options={opts}
          />
        </div>
        <ProductPicker
          locationId={from ? Number(from) : undefined}
          onPick={(l) =>
            setLines((ls) => (ls.some((x) => x.l.product.id === l.product.id) ? ls : [...ls, { l, qty: '' }]))
          }
        />
        {lines.map((x, i) => (
          <div key={x.l.product.id} className="flex items-end gap-2">
            <div className="min-w-0 flex-1 text-sm">
              <p className="truncate font-medium">{x.l.product.name}</p>
              <p className="text-xs text-slate-500">
                {t('products.onHand')}: {formatNum(x.l.stock.on_hand)}
              </p>
            </div>
            <Input
              className="w-28"
              label={t('common.qty')}
              type="number"
              value={x.qty}
              onChange={(e) =>
                setLines((ls) => ls.map((y, j) => (j === i ? { ...y, qty: e.target.value } : y)))
              }
            />
            <Button
              variant="ghost"
              aria-label={t('common.remove')}
              onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}
            >
              <Trash2 className="h-4 w-4 text-rose-600" />
            </Button>
          </div>
        ))}
        <Input label={t('common.notes')} value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
    </Modal>
  );
}

export default function Transfers() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<Transfer | null>(null);
  const q = useQuery({
    queryKey: ['transfers', page],
    queryFn: () => api.get<Page<Transfer>>('/transfers', { page, page_size: 20 }),
  });
  const act = useMutation({
    mutationFn: ({ id, action }: { id: number; action: string }) =>
      api.post<Transfer>(`/transfers/${id}/${action}`, action === 'cancel' ? { reason: null } : undefined),
    onSuccess: (tr) => {
      toast.success(t('common.saved'));
      setDetail(tr);
      void qc.invalidateQueries({ queryKey: ['transfers'] });
      void qc.invalidateQueries({ queryKey: ['products'] });
    },
    onError: (e) => toast.error(e),
  });
  const actions = (tr: Transfer) => {
    const out: { action: string; label: string; variant?: 'danger' | 'secondary' }[] = [];
    if (tr.status === 'REQUESTED' && can('stock.approve'))
      out.push({ action: 'approve', label: t('transfers.approve') });
    if (tr.status === 'APPROVED') out.push({ action: 'dispatch', label: t('transfers.dispatch') });
    if (tr.status === 'DISPATCHED') out.push({ action: 'receive', label: t('transfers.receive') });
    if (['REQUESTED', 'APPROVED'].includes(tr.status) && can('stock.approve'))
      out.push({ action: 'cancel', label: t('common.cancel'), variant: 'danger' });
    return out;
  };
  return (
    <Card
      title={t('nav.transfers')}
      actions={
        <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>
          {t('transfers.new')}
        </Button>
      }
    >
      <DataTable<Transfer>
        rows={q.data?.items}
        loading={q.isLoading}
        error={q.error}
        rowKey={(r) => r.id}
        onRowClick={async (r) => setDetail(await api.get<Transfer>(`/transfers/${r.id}`))}
        empty={t('transfers.empty')}
        columns={[
          { key: 'transfer_no', header: '#', className: 'font-mono text-xs' },
          {
            key: 'route',
            header: t('transfers.route'),
            render: (r) => `${r.from_location} → ${r.to_location}`,
          },
          { key: 'lines', header: t('nav.products'), align: 'right', render: (r) => r.lines.length },
          { key: 'created_at', header: t('common.date'), render: (r) => formatDateTime(r.created_at) },
          { key: 'status', header: t('common.status'), render: (r) => <StatusBadge status={r.status} /> },
        ]}
      />
      {q.data && <Pagination page={page} pageSize={20} total={q.data.total} onPage={setPage} />}
      <NewTransfer open={open} onClose={() => setOpen(false)} />
      <Modal
        open={!!detail}
        onClose={() => setDetail(null)}
        title={detail?.transfer_no ?? ''}
        footer={
          detail &&
          actions(detail).map((a) => (
            <Button
              key={a.action}
              variant={a.variant}
              loading={act.isPending}
              onClick={() => act.mutate({ id: detail.id, action: a.action })}
            >
              {a.label}
            </Button>
          ))
        }
      >
        {detail && (
          <div className="space-y-3 text-sm">
            <p>
              {detail.from_location} → {detail.to_location} · <StatusBadge status={detail.status} />
            </p>
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {detail.lines.map((l) => (
                <li key={l.id} className="flex justify-between py-1.5">
                  <span>{l.product}</span>
                  <b>{formatNum(l.qty)}</b>
                </li>
              ))}
            </ul>
            {detail.history && (
              <ol className="space-y-1 border-l-2 border-brand-200 pl-3 text-xs">
                {detail.history.map((h, i) => (
                  <li key={i}>
                    <b>{h.to}</b> · {formatDateTime(h.at)}
                    {h.note ? ` · ${h.note}` : ''}
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}
      </Modal>
    </Card>
  );
}
