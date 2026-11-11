import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, Pagination, Select, SkeletonRows, Stat, StatusBadge } from '@/components/ui';
import { api, type Page } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { formatDateTime } from '@/lib/format';
import { useToast } from '@/lib/toast';

export interface AlertRow {
  id: number;
  type: string;
  severity: 'info' | 'warning' | 'critical';
  product_id: number | null;
  product: string | null;
  ref_type: string | null;
  ref_id: number | null;
  message: string;
  data: Record<string, unknown> | null;
  status: string;
  resolution: string | null;
  created_at: string;
}

export const ALERT_TYPES = ['low_stock', 'out_of_stock', 'expiry_warning', 'expiry_critical', 'expired', 'dead_stock', 'anomaly',
  'late_delivery', 'approval_pending', 'three_way_mismatch', 'forecast_drift', 'suggestion_rejected', 'info'];

export function alertLink(a: AlertRow): string | null {
  if (a.ref_type === 'purchase_order' && a.ref_id) return `/orders/${a.ref_id}`;
  if (a.ref_type === 'purchase_request' && a.ref_id) return `/approvals?pr=${a.ref_id}`;
  if (a.type.startsWith('expir')) return '/expiry';
  if (a.product_id) return `/products/${a.product_id}`;
  return null;
}

export default function Alerts({ embedded, type }: { embedded?: boolean; type?: string } = {}) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [sp, setSp] = useSearchParams();
  const [page, setPage] = useState(1);
  const f = { type: type ?? sp.get('type') ?? '', severity: sp.get('severity') ?? '', status: sp.get('status') ?? 'open,acknowledged' };
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); setSp(n, { replace: true }); setPage(1); };
  const summary = useQuery({ queryKey: ['alerts', 'summary'], queryFn: () => api.get<{ open: number; by_type: Record<string, number>; by_severity: Record<string, number> }>('/alerts/summary') });
  const list = useQuery({ queryKey: ['alerts', f, page], queryFn: () => api.get<Page<AlertRow>>('/alerts', { ...f, page, page_size: 30 }) });
  const act = useMutation({
    mutationFn: ({ id, action, text }: { id: number; action: 'ack' | 'resolve'; text?: string }) => api.post(`/alerts/${id}/${action}`, action === 'resolve' ? { text: text ?? null } : undefined),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['alerts'] }); toast.success(t('common.saved')); },
    onError: (e) => toast.error(e),
  });
  const tone = (s: string) => (s === 'critical' ? 'red' : s === 'warning' ? 'amber' : 'blue') as 'red' | 'amber' | 'blue';
  return (
    <div className="space-y-4">
      {!embedded && <PageHeader title={t('nav.alerts')} subtitle={t('alerts.subtitle')} />}
      <div className={embedded ? 'hidden' : 'grid grid-cols-3 gap-3'}>
        <Stat label={t('alerts.open')} value={summary.data?.open ?? '—'} />
        <Stat label={t('status.critical')} value={summary.data?.by_severity.critical ?? 0} tone="red" />
        <Stat label={t('status.warning')} value={summary.data?.by_severity.warning ?? 0} tone="amber" />
      </div>
      <Card>
        <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
          <Select disabled={!!type} value={f.type} onChange={(e) => set('type', e.target.value)} placeholder={t('alerts.allTypes')} aria-label={t('stock.type')}
            options={ALERT_TYPES.map((x) => ({ value: x, label: `${t(`alertType.${x}`)}${summary.data?.by_type[x] ? ` (${summary.data.by_type[x]})` : ''}` }))} />
          <Select value={f.severity} onChange={(e) => set('severity', e.target.value)} placeholder={t('alerts.allSeverities')} aria-label={t('alerts.severity')}
            options={['critical', 'warning', 'info'].map((x) => ({ value: x, label: t(`status.${x}`) }))} />
          <Select value={f.status} onChange={(e) => set('status', e.target.value)} aria-label={t('common.status')}
            options={[{ value: 'open,acknowledged', label: t('alerts.active') }, { value: 'open', label: t('status.open') }, { value: 'acknowledged', label: t('status.acknowledged') }, { value: 'resolved', label: t('status.resolved') }]} />
        </div>
        {list.error ? <ErrorState error={list.error} onRetry={() => list.refetch()} /> : !list.data ? <SkeletonRows rows={6} cols={2} /> : list.data.items.length === 0 ? <EmptyState title={t('alerts.none')} /> : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {list.data.items.map((a) => {
              const link = alertLink(a);
              const suggestions = (a.data?.suggestions as string[] | undefined) ?? [];
              return (
                <li key={a.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start">
                  <div className="flex shrink-0 gap-1.5 sm:w-48 sm:flex-col sm:items-start">
                    <Badge tone={tone(a.severity)}>{t(`status.${a.severity}`)}</Badge>
                    <span className="text-xs font-medium">{t(`alertType.${a.type}`)}</span>
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm">{a.message}</p>
                    {suggestions.length > 0 && <ul className="mt-1 list-inside list-disc text-xs text-slate-600 dark:text-slate-400">{suggestions.map((s) => <li key={s}>{s}</li>)}</ul>}
                    <p className="mt-1 text-xs text-slate-400">{formatDateTime(a.created_at)}{a.product ? ` · ${a.product}` : ''}{a.resolution ? ` · ${a.resolution}` : ''}</p>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-1.5">
                    {link && <Link to={link}><Button size="sm" variant="secondary">{t('common.view')}</Button></Link>}
                    {can('alerts.write') && a.status === 'open' && <Button size="sm" variant="secondary" onClick={() => act.mutate({ id: a.id, action: 'ack' })}>{t('alerts.ack')}</Button>}
                    {can('alerts.write') && a.status !== 'resolved' && (a.type === 'anomaly' ? (
                      <>
                        <Button size="sm" variant="success" onClick={() => act.mutate({ id: a.id, action: 'resolve', text: 'valid' })}>{t('alerts.markValid')}</Button>
                        <Button size="sm" variant="danger" onClick={() => act.mutate({ id: a.id, action: 'resolve', text: 'investigate' })}>{t('alerts.investigate')}</Button>
                      </>
                    ) : <Button size="sm" onClick={() => act.mutate({ id: a.id, action: 'resolve', text: 'resolved' })}>{t('alerts.resolve')}</Button>)}
                    {a.status !== 'open' && <StatusBadge status={a.status} />}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {list.data && <Pagination page={page} pageSize={30} total={list.data.total} onPage={setPage} />}
      </Card>
    </div>
  );
}
