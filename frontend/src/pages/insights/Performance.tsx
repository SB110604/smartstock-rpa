import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Badge, Card, DataTable, ErrorState, SkeletonRows, Stat } from '@/components/ui';
import { api } from '@/lib/api';
import { axisProps, tooltipStyle, useChartColors } from '@/lib/chart';
import { formatDate, formatDateTime, formatNum } from '@/lib/format';

interface Perf {
  accuracy: { date: string; mape: number; model_version: string }[];
  drift: { rolling_mape: number | null; training_mape: number | null; threshold: number | null; drift: boolean; model_version: string | null };
  suggestions: { week: string; suggestions: number; acceptance_pct: number | null; accepted_as_is_pct: number | null; avg_correction: number | null }[];
  totals: { suggestions: number; acceptance_pct: number | null; avg_correction: number | null; rejected: number };
  models: { version: string; trained_at: string; is_active: boolean; notes: string | null; mape: number | null; mape_baseline: number | null; incumbent_mape: number | null }[];
}

function MiniLine({ data, dataKey, name, color, unit, reference, refLabel, domain }: {
  data: object[]; dataKey: string; name: string; color: string; unit?: string; reference?: number | null; refLabel?: string;
  domain?: [number | string, number | string];
}) {
  const c = useChartColors();
  return (
    <div className="h-56" role="img" aria-label={name}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
          <CartesianGrid stroke={c.grid} vertical={false} />
          <XAxis dataKey="x" minTickGap={24} {...axisProps(c)} />
          <YAxis domain={domain ?? ['auto', 'auto']} {...axisProps(c)} />
          <Tooltip {...tooltipStyle(c)} formatter={(v: number) => [`${formatNum(v)}${unit ?? ''}`, name]} />
          {reference != null && <ReferenceLine y={reference} stroke={c.status.critical} strokeDasharray="4 3"
            label={{ value: refLabel, fill: c.muted, fontSize: 11, position: 'insideTopRight' }} />}
          <Line dataKey={dataKey} name={name} stroke={color} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function Performance() {
  const { t } = useTranslation();
  const c = useChartColors();
  const q = useQuery({ queryKey: ['performance'], queryFn: () => api.get<Perf>('/insights/performance') });
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <SkeletonRows rows={8} />;
  const d = q.data;
  const acc = d.accuracy.map((a) => ({ x: formatDate(a.date).slice(0, 5), mape: a.mape }));
  const weeks = d.suggestions.map((s) => ({ ...s, x: s.week.replace(/^\d{4}-/, '') }));
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={t('perf.rollingMape')} value={d.drift.rolling_mape != null ? `${d.drift.rolling_mape}%` : '—'}
          hint={`${t('perf.training')} ${d.drift.training_mape ?? '—'}%`} tone={d.drift.drift ? 'red' : 'green'} />
        <Stat label={t('perf.acceptance')} value={d.totals.acceptance_pct != null ? `${d.totals.acceptance_pct}%` : '—'}
          hint={t('perf.ofSuggestions', { n: d.totals.suggestions })} />
        <Stat label={t('perf.avgCorrection')} value={d.totals.avg_correction != null ? `×${d.totals.avg_correction}` : '—'} hint={t('perf.correctionHint')} />
        <Stat label={t('perf.models')} value={d.models.length} hint={d.drift.model_version ?? ''} />
      </div>
      <Card title={t('perf.mapeTrend')} actions={d.drift.drift ? <Badge tone="red">{t('perf.drift')}</Badge> : <Badge tone="green">{t('perf.noDrift')}</Badge>}>
        <MiniLine data={acc} dataKey="mape" name="MAPE" unit="%" color={c.series[0]} reference={d.drift.threshold} refLabel={t('perf.threshold')} domain={[0, 'auto']} />
        <p className="mt-2 text-xs text-slate-500">{t('perf.mapeHint')}</p>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t('perf.acceptanceTrend')}>
          <MiniLine data={weeks} dataKey="acceptance_pct" name={t('perf.acceptance')} unit="%" color={c.series[2]} domain={[0, 100]} />
        </Card>
        <Card title={t('perf.correctionTrend')}>
          <MiniLine data={weeks} dataKey="avg_correction" name={t('perf.avgCorrection')} color={c.series[6]} reference={1} refLabel="×1.0" />
        </Card>
      </div>
      <Card title={t('perf.versions')}>
        <DataTable rows={[...d.models].reverse()} rowKey={(m) => m.version}
          columns={[
            { key: 'version', header: t('insights.version'), className: 'font-mono text-xs' },
            { key: 'trained_at', header: t('insights.trained'), render: (m) => formatDateTime(m.trained_at) },
            { key: 'mape', header: 'MAPE', align: 'right', render: (m) => (m.mape != null ? `${m.mape}%` : '—') },
            { key: 'mape_baseline', header: 'MA-28', align: 'right', render: (m) => (m.mape_baseline != null ? `${m.mape_baseline}%` : '—') },
            { key: 'notes', header: t('common.notes'), render: (m) => <span className="whitespace-normal text-xs">{m.notes}</span> },
            { key: 'is_active', header: t('common.status'), render: (m) => (m.is_active ? <Badge tone="green">{t('insights.active')}</Badge> : <Badge>{t('insights.retired')}</Badge>) },
          ]} />
      </Card>
    </div>
  );
}
