import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Plus } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ScanButton, ScannerModal } from '@/components/Scanner';
import { Badge, Button, Card, DataTable, Modal, Select, Stat, StatusBadge, Textarea } from '@/components/ui';
import { useCategories } from '@/hooks/useMasters';
import { api, type Page } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { formatDateTime, formatINR, formatNum } from '@/lib/format';
import { useToast } from '@/lib/toast';

interface CountLine {
  line_id: number;
  product_id: number;
  product: string;
  sku: string;
  batch_id: number | null;
  system_qty: number;
  counted_qty: number | null;
  variance: number | null;
  variance_value: number;
}
interface CountDetail {
  id: number;
  location: string;
  status: string;
  note: string | null;
  created_at: string;
  lines: CountLine[];
  summary: {
    lines: number;
    counted: number;
    with_variance: number;
    variance_value: number;
    accuracy_pct: number | null;
  };
}
interface CountRow {
  id: number;
  location: string;
  status: string;
  created_at: string;
  lines: number;
  counted: number;
  with_variance: number;
  variance_value: number;
}

function CountSheet({ id, onBack }: { id: number; onBack: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const { can } = useAuth();
  const [scan, setScan] = useState(false);
  const [draft, setDraft] = useState<Record<number, string>>({});
  const q = useQuery({
    queryKey: ['counts', id],
    queryFn: () => api.get<CountDetail>(`/stock-counts/${id}`),
  });
  useEffect(() => {
    if (q.data)
      setDraft(
        Object.fromEntries(
          q.data.lines.map((l) => [l.line_id, l.counted_qty === null ? '' : String(l.counted_qty)]),
        ),
      );
  }, [q.data]);
  const save = useMutation({
    mutationFn: () =>
      api.patch<CountDetail>(`/stock-counts/${id}`, {
        entries: Object.entries(draft).map(([line_id, v]) => ({
          line_id: Number(line_id),
          counted_qty: v === '' ? null : Number(v),
        })),
      }),
    onSuccess: (d) => {
      qc.setQueryData(['counts', id], d);
      toast.success(t('common.saved'));
    },
    onError: (e) => toast.error(e),
  });
  const complete = useMutation({
    mutationFn: async () => {
      await save.mutateAsync();
      return api.post<CountDetail & { result: { adjustments: number; variance_value: number } }>(
        `/stock-counts/${id}/complete`,
      );
    },
    onSuccess: (d) => {
      qc.setQueryData(['counts', id], d);
      toast.success(t('counts.completed', { n: d.result.adjustments }));
      void qc.invalidateQueries({ queryKey: ['products'] });
      void qc.invalidateQueries({ queryKey: ['counts'] });
    },
    onError: (e) => toast.error(e),
  });
  const onScan = (code: string) => {
    setScan(false);
    const sku = code.split('|')[0];
    const line = q.data?.lines.find((l) => l.sku === sku);
    if (!line) return toast.error(t('counts.notInCount', { code }));
    setDraft((d) => ({ ...d, [line.line_id]: String((Number(d[line.line_id]) || 0) + 1) }));
    document.getElementById(`cnt-${line.line_id}`)?.focus();
  };
  const d = q.data;
  const open = d?.status === 'in_progress';
  return (
    <div className="space-y-3">
      <button className="inline-flex items-center gap-1 text-sm text-slate-500" onClick={onBack}>
        <ArrowLeft className="h-4 w-4" />
        {t('counts.title')}
      </button>
      {d && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label={t('counts.lines')} value={`${d.summary.counted} / ${d.summary.lines}`} />
          <Stat
            label={t('counts.withVariance')}
            value={d.summary.with_variance}
            tone={d.summary.with_variance ? 'amber' : 'green'}
          />
          <Stat
            label={t('counts.varianceValue')}
            value={formatINR(d.summary.variance_value)}
            tone={d.summary.variance_value < 0 ? 'red' : undefined}
          />
          <Stat
            label={t('counts.accuracy')}
            value={d.summary.accuracy_pct === null ? '—' : `${d.summary.accuracy_pct}%`}
          />
        </div>
      )}
      <Card
        title={d ? `${t('counts.count')} #${d.id} · ${d.location}` : ''}
        actions={
          d && (
            <>
              <StatusBadge status={d.status === 'in_progress' ? 'open' : 'closed'} />
              {open && <ScanButton onClick={() => setScan(true)} />}
              {open && (
                <Button variant="secondary" loading={save.isPending} onClick={() => save.mutate()}>
                  {t('common.save')}
                </Button>
              )}
              {open && can('stock.approve') && (
                <Button loading={complete.isPending} onClick={() => complete.mutate()}>
                  {t('counts.complete')}
                </Button>
              )}
            </>
          )
        }
      >
        <DataTable<CountLine>
          rows={d?.lines}
          loading={q.isLoading}
          error={q.error}
          rowKey={(l) => l.line_id}
          columns={[
            {
              key: 'product',
              header: t('common.product'),
              render: (l) => (
                <div>
                  <p className="font-medium">{l.product}</p>
                  <p className="text-xs text-slate-500">
                    {l.sku}
                    {l.batch_id ? ` · #${l.batch_id}` : ''}
                  </p>
                </div>
              ),
            },
            {
              key: 'system_qty',
              header: t('counts.system'),
              align: 'right',
              render: (l) => formatNum(l.system_qty),
            },
            {
              key: 'counted',
              header: t('counts.counted'),
              align: 'right',
              render: (l) =>
                open ? (
                  <input
                    id={`cnt-${l.line_id}`}
                    className="input w-24 text-right"
                    type="number"
                    min="0"
                    step="0.001"
                    value={draft[l.line_id] ?? ''}
                    aria-label={`${t('counts.counted')} ${l.product}`}
                    onChange={(e) => setDraft((x) => ({ ...x, [l.line_id]: e.target.value }))}
                  />
                ) : (
                  formatNum(l.counted_qty)
                ),
            },
            {
              key: 'variance',
              header: t('counts.variance'),
              align: 'right',
              render: (l) => {
                const v = open
                  ? draft[l.line_id] === '' || draft[l.line_id] === undefined
                    ? null
                    : Number(draft[l.line_id]) - l.system_qty
                  : l.variance;
                return v === null ? (
                  '—'
                ) : (
                  <Badge tone={v === 0 ? 'green' : v < 0 ? 'red' : 'amber'}>
                    {v > 0 ? '+' : ''}
                    {formatNum(v)}
                  </Badge>
                );
              },
            },
            {
              key: 'variance_value',
              header: t('counts.varianceValue'),
              align: 'right',
              render: (l) => formatINR(l.variance_value),
            },
          ]}
        />
      </Card>
      <ScannerModal open={scan} onClose={() => setScan(false)} onDetected={onScan} />
    </div>
  );
}

export default function Counts({ locationId }: { locationId?: number }) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const cats = useCategories();
  const [current, setCurrent] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const [cat, setCat] = useState('');
  const [note, setNote] = useState('');
  const list = useQuery({
    queryKey: ['counts', 'list'],
    queryFn: () => api.get<Page<CountRow>>('/stock-counts', { page_size: 50 }),
  });
  const start = useMutation({
    mutationFn: () =>
      api.post<CountDetail>('/stock-counts', {
        location_id: locationId,
        category_id: cat ? Number(cat) : null,
        note: note || null,
      }),
    onSuccess: (c) => {
      setOpen(false);
      setCurrent(c.id);
      void qc.invalidateQueries({ queryKey: ['counts'] });
    },
    onError: (e) => toast.error(e),
  });
  if (current) return <CountSheet id={current} onBack={() => setCurrent(null)} />;
  return (
    <Card
      title={t('counts.title')}
      actions={
        <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>
          {t('counts.start')}
        </Button>
      }
    >
      <DataTable<CountRow>
        rows={list.data?.items}
        loading={list.isLoading}
        error={list.error}
        rowKey={(c) => c.id}
        onRowClick={(c) => setCurrent(c.id)}
        empty={t('counts.empty')}
        columns={[
          { key: 'id', header: '#' },
          { key: 'location', header: t('stock.location') },
          { key: 'created_at', header: t('common.date'), render: (c) => formatDateTime(c.created_at) },
          {
            key: 'progress',
            header: t('counts.lines'),
            align: 'right',
            render: (c) => `${c.counted}/${c.lines}`,
          },
          { key: 'with_variance', header: t('counts.withVariance'), align: 'right' },
          {
            key: 'variance_value',
            header: t('counts.varianceValue'),
            align: 'right',
            render: (c) => formatINR(c.variance_value),
          },
          {
            key: 'status',
            header: t('common.status'),
            render: (c) => <StatusBadge status={c.status === 'in_progress' ? 'open' : 'closed'} />,
          },
        ]}
      />
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={t('counts.start')}
        footer={
          <Button loading={start.isPending} disabled={!locationId} onClick={() => start.mutate()}>
            {t('counts.start')}
          </Button>
        }
      >
        <div className="space-y-3">
          <Select
            label={t('products.category')}
            value={cat}
            onChange={(e) => setCat(e.target.value)}
            placeholder={t('products.allCategories')}
            options={(cats.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
          />
          <Textarea label={t('common.notes')} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
      </Modal>
    </Card>
  );
}
