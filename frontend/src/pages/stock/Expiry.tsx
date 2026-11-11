import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeftRight, Percent, Trash2, Undo2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { Batch } from '@/api/types';
import { Badge, Button, Card, EmptyState, ErrorState, Input, Modal, PageHeader, SkeletonRows, Stat, Tabs, Textarea } from '@/components/ui';
import { useLocations } from '@/hooks/useMasters';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { axisProps, tooltipStyle, useChartColors } from '@/lib/chart';
import { formatDate, formatINR, formatNum } from '@/lib/format';
import { useToast } from '@/lib/toast';
import { NewReturn } from '@/pages/purchasing/Returns';

export interface ExpiryRow {
  batch_id: number;
  product_id: number;
  product: string;
  sku: string;
  unit: string;
  batch_no: string;
  location_id: number;
  location: string;
  expiry_date: string;
  days_to_expiry: number;
  bucket: 'expired' | 'critical' | 'warning';
  qty: number;
  value: number;
  avg_daily_sales: number;
  projected_sell: number;
  surplus: number;
  at_risk: boolean;
  markdown_pct: number;
  is_blocked: boolean;
  supplier_id: number | null;
  suggested_markdown: number;
  actions: string[];
  suggestion: string;
}
interface Overview {
  groups: Record<'expired' | 'critical' | 'warning', ExpiryRow[]>;
  totals: Record<string, { batches: number; value: number; at_risk: number }>;
  value_by_week: { week: string; value: number }[];
}

type Action = { kind: 'markdown' | 'write_off' | 'transfer' | 'return'; row: ExpiryRow } | null;

export default function Expiry() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const c = useChartColors();
  const locs = useLocations();
  const [tab, setTab] = useState<'expired' | 'critical' | 'warning'>('critical');
  const [action, setAction] = useState<Action>(null);
  const [pct, setPct] = useState('');
  const [reason, setReason] = useState('');
  const [qty, setQty] = useState('');
  const q = useQuery({ queryKey: ['expiry'], queryFn: () => api.get<Overview>('/expiry') });
  const done = () => {
    toast.success(t('common.saved'));
    setAction(null);
    void qc.invalidateQueries({ queryKey: ['expiry'] });
    void qc.invalidateQueries({ queryKey: ['alerts'] });
  };
  const exec = useMutation({
    mutationFn: async () => {
      const r = action!.row;
      if (action!.kind === 'markdown') return api.post('/stock/markdown', { batch_id: r.batch_id, markdown_pct: Number(pct) });
      if (action!.kind === 'write_off') return api.post('/stock/write-off', { batch_id: r.batch_id, qty: Number(qty) || null, reason });
      const other = (locs.data ?? []).find((l) => l.id !== r.location_id);
      return api.post('/transfers', { from_location_id: r.location_id, to_location_id: other?.id, note: reason || t('expiry.transferNote'),
        lines: [{ product_id: r.product_id, batch_id: r.batch_id, qty: Number(qty) }] });
    },
    onSuccess: done,
    onError: (e) => toast.error(e),
  });
  const open = (kind: NonNullable<Action>['kind'], row: ExpiryRow) => {
    setAction({ kind, row });
    setPct(String(row.suggested_markdown || 10));
    setQty(String(kind === 'transfer' ? Math.ceil(row.surplus) || row.qty : row.qty));
    setReason(kind === 'write_off' ? (row.bucket === 'expired' ? t('expiry.expiredReason') : '') : '');
  };
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <SkeletonRows rows={8} />;
  const rows = q.data.groups[tab];
  const manage = can('stock.approve');
  return (
    <div className="space-y-4">
      <PageHeader title={t('nav.expiry')} subtitle={t('expiry.subtitle')} />
      <div className="grid grid-cols-3 gap-3">
        <Stat label={t('status.expired')} value={formatINR(q.data.totals.expired.value, false)} hint={`${q.data.totals.expired.batches} ${t('expiry.batches')}`} tone="red" />
        <Stat label={t('status.critical')} value={formatINR(q.data.totals.critical.value, false)} hint={`${q.data.totals.critical.at_risk} ${t('expiry.atRisk')}`} tone="red" />
        <Stat label={t('status.warning')} value={formatINR(q.data.totals.warning.value, false)} hint={`${q.data.totals.warning.at_risk} ${t('expiry.atRisk')}`} tone="amber" />
      </div>
      <Card title={t('expiry.byWeek')}>
        <div className="h-48" role="img" aria-label={t('expiry.byWeek')}>
          <ResponsiveContainer>
            <BarChart data={q.data.value_by_week} margin={{ left: 0, right: 8, top: 4 }}>
              <CartesianGrid stroke={c.grid} vertical={false} />
              <XAxis dataKey="week" {...axisProps(c)} />
              <YAxis {...axisProps(c)} tickFormatter={(v) => `₹${+(v / 1000).toFixed(1)}k`} />
              <Tooltip {...tooltipStyle(c)} formatter={(v: number) => [formatINR(v), t('expiry.value')]} cursor={{ fill: c.grid, opacity: 0.4 }} />
              <Bar dataKey="value" fill={c.series[0]} radius={[4, 4, 0, 0]} maxBarSize={36} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>
      <Tabs value={tab} onChange={setTab} tabs={(['expired', 'critical', 'warning'] as const).map((k) => ({ value: k, label: t(`status.${k}`), count: q.data.totals[k].batches }))} />
      {rows.length === 0 ? <EmptyState title={t('expiry.none')} /> : (
        <ul className="space-y-2">
          {rows.map((r) => (
            <li key={r.batch_id} className="card flex flex-col gap-2 p-3 md:flex-row md:items-center">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold"><Link className="hover:underline" to={`/products/${r.product_id}`}>{r.product}</Link>
                  <span className="ml-2 text-xs font-normal text-slate-500">{r.batch_no} · {r.location}</span></p>
                <p className="text-xs text-slate-600 dark:text-slate-400">
                  {t('stock.expiry')} {formatDate(r.expiry_date)} ({r.days_to_expiry <= 0 ? t('status.expired') : t('expiry.daysLeft', { n: r.days_to_expiry })}) ·
                  {' '}{formatNum(r.qty)} {r.unit} · {formatINR(r.value)} · {t('expiry.sells', { n: formatNum(r.avg_daily_sales) })} → {t('expiry.projected', { n: formatNum(r.projected_sell) })}
                </p>
                {r.suggestion && <p className="mt-1 text-xs text-violet-700 dark:text-violet-300">{r.suggestion}</p>}
                <div className="mt-1 flex gap-1">
                  {r.at_risk && <Badge tone="red">{t('expiry.atRisk')}</Badge>}
                  {r.markdown_pct > 0 && <Badge tone="amber">−{r.markdown_pct}%</Badge>}
                  {r.is_blocked && <Badge tone="red">{t('stock.blocked')}</Badge>}
                </div>
              </div>
              {manage && (
                <div className="flex flex-wrap gap-1.5">
                  {r.bucket !== 'expired' && <Button size="sm" variant={r.actions.includes('markdown') ? 'primary' : 'secondary'} icon={<Percent className="h-3.5 w-3.5" />} onClick={() => open('markdown', r)}>{t('expiry.markdown')}</Button>}
                  {r.bucket !== 'expired' && (locs.data?.length ?? 0) > 1 && <Button size="sm" variant="secondary" icon={<ArrowLeftRight className="h-3.5 w-3.5" />} onClick={() => open('transfer', r)}>{t('expiry.transfer')}</Button>}
                  {can('returns.manage') && <Button size="sm" variant="secondary" icon={<Undo2 className="h-3.5 w-3.5" />} onClick={() => open('return', r)}>{t('expiry.return')}</Button>}
                  <Button size="sm" variant={r.bucket === 'expired' ? 'danger' : 'secondary'} icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => open('write_off', r)}>{t('expiry.writeOff')}</Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <Modal open={!!action && action.kind !== 'return'} onClose={() => setAction(null)} title={action ? `${t(`expiry.${action.kind === 'write_off' ? 'writeOff' : action.kind}`)} — ${action.row.product}` : ''}
        footer={<Button variant={action?.kind === 'write_off' ? 'danger' : 'primary'} loading={exec.isPending}
          disabled={action?.kind === 'write_off' ? reason.trim().length < 3 : action?.kind === 'markdown' ? !(Number(pct) >= 0) : !(Number(qty) > 0)}
          onClick={() => exec.mutate()}>{t('common.confirm')}</Button>}>
        {action?.kind === 'markdown' && <Input label={t('expiry.markdownPct')} type="number" min={0} max={90} value={pct} onChange={(e) => setPct(e.target.value)} hint={t('expiry.markdownHint')} />}
        {(action?.kind === 'write_off' || action?.kind === 'transfer') && (
          <div className="space-y-3">
            <Input label={t('common.qty')} type="number" value={qty} onChange={(e) => setQty(e.target.value)} />
            <Textarea label={t('common.reason')} value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
        )}
      </Modal>
      {action?.kind === 'return' && (
        <NewReturn open onClose={() => { setAction(null); void qc.invalidateQueries({ queryKey: ['expiry'] }); }}
          preset={{ supplierId: action.row.supplier_id ?? undefined, batch: { id: action.row.batch_id, product_id: action.row.product_id, location_id: action.row.location_id,
            batch_no: action.row.batch_no, expiry_date: action.row.expiry_date, qty_on_hand: action.row.qty, product_name: action.row.product } as Batch }} />
      )}
    </div>
  );
}
