import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bot, Play, PlayCircle } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { ForecastChart } from '@/components/ForecastChart';
import { Badge, Button, Card, DataTable, EmptyState, ErrorState, Modal, PageHeader, Pagination, Select, SkeletonRows, StatusBadge, Tabs } from '@/components/ui';
import { useProductOptions } from '@/hooks/useMasters';
import { api, type Page } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useChartColors } from '@/lib/chart';
import { formatDateTime, formatINR, titleCase } from '@/lib/format';
import { useToast } from '@/lib/toast';
import Alerts from '@/pages/Alerts';
import Performance from './Performance';

interface Run {
  id: number;
  agent: string;
  status: string;
  started_at: string;
  seconds: number | null;
  items: number;
  summary: Record<string, unknown> | null;
  error: string | null;
  triggered_by: string;
  pipeline_id: string | null;
}
interface AgentInfo {
  name: string;
  title: string;
  description: string;
  in_pipeline: boolean;
  order: number | null;
  last_run: Run | null;
  successful_runs: number;
}

function SummaryChips({ summary }: { summary: Record<string, unknown> | null }) {
  if (!summary) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {Object.entries(summary)
        .filter(([k, v]) => k !== 'trace' && (typeof v === 'number' || typeof v === 'string'))
        .slice(0, 8)
        .map(([k, v]) => (
          <span key={k} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            {titleCase(k)}: <b>{String(v)}</b>
          </span>
        ))}
    </div>
  );
}

export function AgentsPanel() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [result, setResult] = useState<{ runs: { agent: string; status: string; summary: Record<string, unknown> | null; error: string | null }[] } | null>(null);
  const q = useQuery({ queryKey: ['agents'], queryFn: () => api.get<AgentInfo[]>('/agents') });
  const run = useMutation({
    mutationFn: (name: string | null) => api.post<typeof result & object>(name ? `/agents/${name}/run` : '/agents/pipeline/run'),
    onSuccess: (r) => {
      setResult(r);
      void qc.invalidateQueries();
      toast.success(t('insights.runDone'));
    },
    onError: (e) => toast.error(e),
  });
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <SkeletonRows rows={7} />;
  const agents = [...q.data].sort((a, b) => (a.order ?? 99) - (b.order ?? 99));
  return (
    <div className="space-y-4">
      <Card title={t('insights.pipeline')} actions={can('agents.run') && (
        <Button icon={<PlayCircle className="h-4 w-4" />} loading={run.isPending && run.variables === null} onClick={() => run.mutate(null)}>{t('insights.runPipeline')}</Button>
      )}>
        <p className="mb-3 text-xs text-slate-500">{t('insights.pipelineHint')}</p>
        <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {agents.map((a) => (
            <li key={a.name} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
              <div className="flex items-start justify-between gap-2">
                <p className="flex items-center gap-1.5 text-sm font-semibold">
                  <Bot className="h-4 w-4 text-violet-600" />
                  {a.order ? `${a.order}. ` : ''}{t(`agent.${a.name}`, { defaultValue: a.title })}
                </p>
                {a.last_run && <StatusBadge status={a.last_run.status} />}
              </div>
              <p className="mt-1 text-xs text-slate-500">{t(`agentDesc.${a.name}`, { defaultValue: a.description })}</p>
              {a.last_run && (
                <div className="mt-2 space-y-1">
                  <p className="text-[11px] text-slate-400">{formatDateTime(a.last_run.started_at)} · {a.last_run.seconds ?? '—'}s · {a.last_run.triggered_by}</p>
                  <SummaryChips summary={a.last_run.summary} />
                  {a.last_run.error && <p className="text-xs text-rose-600">{a.last_run.error}</p>}
                </div>
              )}
              {can('agents.run') && (a.name !== 'learning' || can('models.retrain')) && (
                <Button className="mt-2" size="sm" variant="secondary" icon={<Play className="h-3.5 w-3.5" />}
                  loading={run.isPending && run.variables === a.name} onClick={() => run.mutate(a.name)}>{t('insights.runNow')}</Button>
              )}
            </li>
          ))}
        </ol>
      </Card>
      <Modal open={!!result} onClose={() => setResult(null)} title={t('insights.runResult')} wide>
        <ul className="space-y-2">
          {result?.runs.map((r, i) => (
            <li key={i} className="rounded border border-slate-200 p-2 text-sm dark:border-slate-700">
              <div className="flex items-center gap-2"><StatusBadge status={r.status} /><b>{t(`agent.${r.agent}`, { defaultValue: r.agent })}</b></div>
              <div className="mt-1"><SummaryChips summary={r.summary} /></div>
              {r.error && <p className="text-xs text-rose-600">{r.error}</p>}
            </li>
          ))}
        </ul>
      </Modal>
    </div>
  );
}

function RunHistory() {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const [agent, setAgent] = useState('');
  const q = useQuery({ queryKey: ['agent-runs', agent, page], queryFn: () => api.get<Page<Run>>('/agent-runs', { agent, page, page_size: 25 }) });
  return (
    <Card title={t('insights.history')} actions={
      <Select value={agent} onChange={(e) => { setAgent(e.target.value); setPage(1); }} placeholder={t('common.all')} aria-label={t('insights.agent')}
        options={['stock_monitor', 'expiry', 'decision', 'supplier', 'auto_order', 'tracking', 'anomaly', 'learning'].map((a) => ({ value: a, label: t(`agent.${a}`) }))} />
    }>
      <DataTable<Run> rows={q.data?.items} loading={q.isLoading} error={q.error} rowKey={(r) => r.id}
        columns={[
          { key: 'started_at', header: t('common.date'), render: (r) => formatDateTime(r.started_at) },
          { key: 'agent', header: t('insights.agent'), render: (r) => t(`agent.${r.agent}`, { defaultValue: r.agent }) },
          { key: 'triggered_by', header: t('insights.trigger') },
          { key: 'seconds', header: 's', align: 'right' },
          { key: 'items', header: t('insights.items'), align: 'right' },
          { key: 'summary', header: t('insights.summary'), render: (r) => <div className="max-w-md whitespace-normal">{r.error ? <span className="text-xs text-rose-600">{r.error}</span> : <SummaryChips summary={r.summary} />}</div> },
          { key: 'status', header: t('common.status'), render: (r) => <StatusBadge status={r.status} /> },
        ]} />
      {q.data && <Pagination page={page} pageSize={25} total={q.data.total} onPage={setPage} />}
    </Card>
  );
}

function Forecasts() {
  const { t } = useTranslation();
  const products = useProductOptions();
  const [pid, setPid] = useState<string>('');
  const selected = (products.data ?? []).find((p) => String(p.id) === pid) ?? products.data?.[0];
  return (
    <Card title={t('insights.forecastTitle')} actions={
      <Select className="w-64" value={selected ? String(selected.id) : ''} onChange={(e) => setPid(e.target.value)} aria-label={t('nav.products')}
        options={(products.data ?? []).map((p) => ({ value: p.id, label: p.name }))} />
    }>
      {selected ? <ForecastChart productId={selected.id} unit={selected.unit} /> : <SkeletonRows rows={6} />}
    </Card>
  );
}

interface Matrix {
  cells: Record<string, { count: number; value: number; products: { id: number; name: string }[] }>;
  advice: Record<string, string>;
}

function AbcXyz() {
  const { t } = useTranslation();
  const c = useChartColors();
  const [cell, setCell] = useState<string | null>(null);
  const q = useQuery({ queryKey: ['abc-xyz'], queryFn: () => api.get<Matrix>('/insights/abc-xyz') });
  if (q.error) return <ErrorState error={q.error} />;
  if (!q.data) return <SkeletonRows rows={4} cols={3} />;
  const max = Math.max(1, ...Object.values(q.data.cells).map((x) => x.count));
  const shade = (n: number) => c.seq[Math.min(c.seq.length - 1, Math.floor((n / max) * (c.seq.length - 1)))];
  const dark = (n: number) => n / max > 0.55;
  return (
    <Card title={t('insights.abcTitle')}>
      <p className="mb-3 text-xs text-slate-500">{t('insights.abcHint')}</p>
      <div className="overflow-x-auto">
        <table className="mx-auto border-separate border-spacing-1 text-sm">
          <thead><tr><th />{['X', 'Y', 'Z'].map((x) => <th key={x} className="px-2 text-xs text-slate-500">{x} · {t(`insights.xyz_${x}`)}</th>)}</tr></thead>
          <tbody>
            {['A', 'B', 'C'].map((a) => (
              <tr key={a}>
                <th className="pr-2 text-left text-xs text-slate-500">{a} · {t(`insights.abc_${a}`)}</th>
                {['X', 'Y', 'Z'].map((x) => {
                  const k = `${a}${x}`;
                  const v = q.data.cells[k];
                  return (
                    <td key={k}>
                      <button className="flex h-24 w-28 flex-col items-center justify-center rounded-lg sm:w-36" style={{ background: shade(v.count), color: dark(v.count) ? '#ffffff' : '#0b0b0b' }}
                        onClick={() => setCell(k)} aria-label={`${k}: ${v.count}`}>
                        <span className="text-lg font-bold">{k}</span>
                        <span className="text-xs">{v.count} · {formatINR(v.value, false)}</span>
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Modal open={!!cell} onClose={() => setCell(null)} title={cell ? `${cell} — ${q.data.advice[cell]}` : ''}>
        <ul className="space-y-1 text-sm">
          {cell && q.data.cells[cell].products.map((p) => <li key={p.id}><Link className="text-brand-700 hover:underline dark:text-brand-400" to={`/products/${p.id}`}>{p.name}</Link></li>)}
          {cell && !q.data.cells[cell].products.length && <li className="text-slate-500">{t('common.noData')}</li>}
        </ul>
      </Modal>
    </Card>
  );
}

function DeadStock() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ['dead-stock'], queryFn: () => api.get<{ alert_id: number; product_id: number; product: string; message: string; value?: number; days_without_sale?: number; suggestions?: string[] }[]>('/insights/dead-stock') });
  if (q.error) return <ErrorState error={q.error} />;
  if (!q.data) return <SkeletonRows rows={4} />;
  if (!q.data.length) return <EmptyState title={t('insights.noDead')} />;
  return (
    <Card title={t('insights.deadTitle')}>
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {q.data.map((d) => (
          <li key={d.alert_id} className="py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Link className="font-medium text-brand-700 hover:underline dark:text-brand-400" to={`/products/${d.product_id}`}>{d.product}</Link>
              <span className="text-sm">{formatINR(d.value ?? 0)} · {d.days_without_sale ?? '—'} {t('insights.daysNoSale')}</span>
            </div>
            <ul className="mt-1 flex flex-wrap gap-1">{(d.suggestions ?? []).map((s) => <Badge key={s} tone="blue">{s}</Badge>)}</ul>
          </li>
        ))}
      </ul>
    </Card>
  );
}

interface ModelRow {
  id: number;
  name: string;
  version: string;
  trained_at: string;
  metrics: Record<string, number | string | null>;
  is_active: boolean;
  notes: string | null;
}

export function Models() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ['models'], queryFn: () => api.get<ModelRow[]>('/models') });
  return (
    <Card title={t('insights.models')}>
      <DataTable<ModelRow> rows={q.data} loading={q.isLoading} error={q.error} rowKey={(m) => m.id}
        columns={[
          { key: 'name', header: t('common.name'), render: (m) => t(`model.${m.name}`, { defaultValue: m.name }) },
          { key: 'version', header: t('insights.version'), className: 'font-mono text-xs' },
          { key: 'trained_at', header: t('insights.trained'), render: (m) => formatDateTime(m.trained_at) },
          { key: 'metrics', header: 'MAPE / RMSE', render: (m) => m.metrics.mape !== undefined ? `${m.metrics.mape}% (MA-28 ${m.metrics.mape_baseline}%) · ${m.metrics.rmse_model}` : `${m.metrics.rows ?? ''} rows` },
          { key: 'notes', header: t('common.notes'), render: (m) => <span className="whitespace-normal text-xs">{m.notes ?? ''}</span> },
          { key: 'is_active', header: t('common.status'), render: (m) => (m.is_active ? <Badge tone="green">{t('insights.active')}</Badge> : <Badge>{t('insights.retired')}</Badge>) },
        ]} />
    </Card>
  );
}

type Tab = 'agents' | 'history' | 'forecasts' | 'abc' | 'dead' | 'anomalies' | 'performance' | 'models';

export default function Insights() {
  const { t } = useTranslation();
  const [sp, setSp] = useSearchParams();
  const tab = (sp.get('tab') ?? 'agents') as Tab;
  const tabs = [
    { value: 'agents', label: t('insights.tabAgents') },
    { value: 'history', label: t('insights.history') },
    { value: 'forecasts', label: t('insights.tabForecasts') },
    { value: 'abc', label: 'ABC / XYZ' },
    { value: 'dead', label: t('insights.tabDead') },
    { value: 'anomalies', label: t('insights.tabAnomalies') },
    { value: 'performance', label: t('perf.tab') },
    { value: 'models', label: t('insights.models') },
  ];
  return (
    <div>
      <PageHeader title={t('nav.insights')} subtitle={t('insights.subtitle')} />
      <Tabs tabs={tabs} value={tab} onChange={(v) => setSp({ tab: v }, { replace: true })} />
      {tab === 'agents' && <AgentsPanel />}
      {tab === 'history' && <RunHistory />}
      {tab === 'forecasts' && <Forecasts />}
      {tab === 'abc' && <AbcXyz />}
      {tab === 'dead' && <DeadStock />}
      {tab === 'anomalies' && <AnomalyAlerts />}
      {tab === 'performance' && <Performance />}
      {tab === 'models' && <Models />}
    </div>
  );
}

function AnomalyAlerts() {
  return <Alerts embedded type="anomaly" />;
}

