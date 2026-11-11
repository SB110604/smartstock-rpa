import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '@/lib/api';
import { axisProps, tooltipStyle, useChartColors } from '@/lib/chart';
import { formatDate, formatNum } from '@/lib/format';
import { ErrorState, KeyValue, SkeletonRows } from './ui';

export interface ForecastData {
  actual: { date: string; actual: number }[];
  forecast: { date: string; predicted: number; lower: number; upper: number }[];
  model: string | null;
  model_version: string | null;
  accuracy: { mape_model: number | null; mape_baseline: number | null; choice: string } | null;
  next_7_days: number;
  next_30_days: number;
}

export function ForecastChart({ productId, unit }: { productId: number; unit: string }) {
  const { t } = useTranslation();
  const c = useChartColors();
  const q = useQuery({ queryKey: ['forecast', productId], queryFn: () => api.get<ForecastData>(`/products/${productId}/forecast`) });
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <SkeletonRows rows={6} />;
  const d = q.data;
  const rows = [
    ...d.actual.map((a) => ({ date: a.date, actual: a.actual })),
    ...d.forecast.map((f) => ({ date: f.date, forecast: f.predicted, band: [f.lower, f.upper] as [number, number] })),
  ];
  return (
    <div className="space-y-3">
      <div className="h-72" role="img" aria-label={t('insights.forecastAria')}>
        <ResponsiveContainer>
          <ComposedChart data={rows} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid stroke={c.grid} vertical={false} />
            <XAxis dataKey="date" tickFormatter={(v) => formatDate(v).slice(0, 5)} minTickGap={24} {...axisProps(c)} />
            <YAxis {...axisProps(c)} allowDecimals={false} />
            <Tooltip {...tooltipStyle(c)} labelFormatter={(v) => formatDate(String(v))}
              formatter={(v: number | number[], name: string) => [Array.isArray(v) ? `${formatNum(v[0])} – ${formatNum(v[1])}` : formatNum(v), name]} />
            <Legend wrapperStyle={{ fontSize: 12, color: c.ink }} />
            <Area dataKey="band" name={t('insights.interval')} stroke="none" fill={c.band} fillOpacity={0.7} isAnimationActive={false} />
            <Line dataKey="actual" name={t('insights.actual')} stroke={c.series[0]} strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="forecast" name={t('insights.forecast')} stroke={c.series[1]} strokeWidth={2} strokeDasharray="5 3" dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <KeyValue items={[
        [t('insights.next7'), `${formatNum(d.next_7_days)} ${unit}`],
        [t('insights.next30'), `${formatNum(d.next_30_days)} ${unit}`],
        [t('insights.method'), d.model === 'hgb' ? t('insights.methodModel') : t('insights.methodBaseline')],
        [t('insights.holdoutMape'), d.accuracy ? `${formatNum(d.accuracy.mape_model)}% vs ${formatNum(d.accuracy.mape_baseline)}% (MA-28)` : '—'],
        [t('insights.version'), d.model_version ?? '—'],
      ]} />
    </div>
  );
}
