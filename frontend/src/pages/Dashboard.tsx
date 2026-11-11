import { useQuery } from '@tanstack/react-query';
import { Bot, PackageCheck, ScanLine } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, SkeletonRows, Stat } from '@/components/ui';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { axisProps, tooltipStyle, useChartColors } from '@/lib/chart';
import { formatDate, formatDateTime, formatINR, formatNum } from '@/lib/format';
import { PortalHome } from '@/pages/portal/Portal';

interface Mgmt {
  role: string;
  kpis: {
    stock_value: number; below_rop: number; out_of_stock: number; near_expiry_value: number; pending_approvals: number; open_pos: number;
    late_deliveries: number; month_purchases: number; inventory_turnover: number | null; ai_acceptance_pct: number | null;
  };
  charts: {
    sales_vs_forecast: { date: string; actual: number | null; forecast: number | null }[];
    stock_value_trend: { date: string; value: number }[];
    fast_movers: { product_id: number; product: string; qty: number; unit: string; revenue: number }[];
    expiry_by_week: { week: string; value: number }[];
    supplier_on_time: { supplier: string; on_time_pct: number; score: number }[];
  };
  alerts: { id: number; type: string; severity: string; message: string; created_at: string }[];
  approvals: { id: number; product: string; qty: number; unit: string; est_total: number; created_by: string; created_at: string }[];
}
interface StaffData {
  receive: { id: number; po_no: string; supplier: string; status: string; eta: string | null; lines: number }[];
  counts: { id: number; location: string; lines: number; counted: number }[];
  expiring: { batch_id: number; product: string; batch_no: string; qty: number; unit: string; days_to_expiry: number; suggestion: string }[];
  summary: { to_receive: number; counts: number; expiring: number; out_of_stock: number };
}

const short = (v: string) => formatDate(v).slice(0, 5);
const kShort = (v: number) => (v >= 100000 ? `${(v / 100000).toFixed(1)}L` : v >= 1000 ? `${+(v / 1000).toFixed(1)}k` : String(Math.round(v)));

function ManagementDashboard({ d }: { d: Mgmt }) {
  const { t } = useTranslation();
  const c = useChartColors();
  const k = d.kpis;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <Stat label={t('dash.stockValue')} value={formatINR(k.stock_value, false)} />
        <Stat label={t('dash.belowRop')} value={k.below_rop} tone={k.below_rop ? 'amber' : undefined} />
        <Stat label={t('dash.outOfStock')} value={k.out_of_stock} tone={k.out_of_stock ? 'red' : 'green'} />
        <Stat label={t('dash.nearExpiry')} value={formatINR(k.near_expiry_value, false)} hint={t('dash.next30')} />
        <Stat label={t('dash.pendingApprovals')} value={k.pending_approvals} tone={k.pending_approvals ? 'amber' : undefined} />
        <Stat label={t('dash.openPos')} value={k.open_pos} />
        <Stat label={t('dash.late')} value={k.late_deliveries} tone={k.late_deliveries ? 'red' : 'green'} />
        <Stat label={t('dash.monthPurchases')} value={formatINR(k.month_purchases, false)} />
        <Stat label={t('dash.turnover')} value={k.inventory_turnover != null ? `${k.inventory_turnover}×` : '—'} hint={t('dash.perYear')} />
        <Stat label={t('dash.aiAcceptance')} value={k.ai_acceptance_pct != null ? `${k.ai_acceptance_pct}%` : '—'} />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title={t('dash.salesVsForecast')}>
          <div className="h-64" role="img" aria-label={t('dash.salesVsForecast')}>
            <ResponsiveContainer>
              <LineChart data={d.charts.sales_vs_forecast} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
                <CartesianGrid stroke={c.grid} vertical={false} />
                <XAxis dataKey="date" tickFormatter={short} minTickGap={28} {...axisProps(c)} />
                <YAxis {...axisProps(c)} tickFormatter={kShort} />
                <Tooltip {...tooltipStyle(c)} labelFormatter={(v) => formatDate(String(v))} formatter={(v: number, n: string) => [formatNum(v), n]} />
                <Legend wrapperStyle={{ fontSize: 12, color: c.ink }} />
                <Line dataKey="actual" name={t('insights.actual')} stroke={c.series[0]} strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line dataKey="forecast" name={t('insights.forecast')} stroke={c.series[1]} strokeWidth={2} strokeDasharray="5 3" dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-slate-500">{t('dash.unitsHint')}</p>
        </Card>
        <Card title={t('dash.stockTrend')}>
          <div className="h-64" role="img" aria-label={t('dash.stockTrend')}>
            <ResponsiveContainer>
              <AreaChart data={d.charts.stock_value_trend} margin={{ top: 8, right: 8, left: -4, bottom: 0 }}>
                <CartesianGrid stroke={c.grid} vertical={false} />
                <XAxis dataKey="date" tickFormatter={short} minTickGap={28} {...axisProps(c)} />
                <YAxis {...axisProps(c)} tickFormatter={(v) => `₹${kShort(v)}`} />
                <Tooltip {...tooltipStyle(c)} labelFormatter={(v) => formatDate(String(v))} formatter={(v: number) => [formatINR(v, false), t('dash.stockValue')]} />
                <Area dataKey="value" stroke={c.series[0]} strokeWidth={2} fill={c.band} fillOpacity={0.6} isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title={t('dash.fastMovers')}>
          <div className="h-72" role="img" aria-label={t('dash.fastMovers')}>
            <ResponsiveContainer>
              <BarChart data={d.charts.fast_movers} layout="vertical" margin={{ left: 8, right: 16 }}>
                <CartesianGrid stroke={c.grid} horizontal={false} />
                <XAxis type="number" {...axisProps(c)} />
                <YAxis type="category" dataKey="product" width={130} {...axisProps(c)} tick={{ fill: c.muted, fontSize: 10 }} />
                <Tooltip {...tooltipStyle(c)} cursor={{ fill: c.grid, opacity: 0.4 }} formatter={(v: number) => [formatNum(v), t('dash.unitsSold')]} />
                <Bar dataKey="qty" fill={c.series[0]} radius={[0, 4, 4, 0]} maxBarSize={18} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <div className="grid gap-4">
          <Card title={t('dash.expiryRisk')}>
            <div className="h-40" role="img" aria-label={t('dash.expiryRisk')}>
              <ResponsiveContainer>
                <BarChart data={d.charts.expiry_by_week} margin={{ top: 4, right: 8, left: -4 }}>
                  <CartesianGrid stroke={c.grid} vertical={false} />
                  <XAxis dataKey="week" {...axisProps(c)} />
                  <YAxis {...axisProps(c)} tickFormatter={(v) => `₹${kShort(v)}`} />
                  <Tooltip {...tooltipStyle(c)} cursor={{ fill: c.grid, opacity: 0.4 }} formatter={(v: number) => [formatINR(v, false), t('expiry.value')]} />
                  <Bar dataKey="value" fill={c.series[3]} radius={[4, 4, 0, 0]} maxBarSize={32} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
          <Card title={t('dash.supplierOnTime')}>
            <div className="h-40" role="img" aria-label={t('dash.supplierOnTime')}>
              <ResponsiveContainer>
                <BarChart data={d.charts.supplier_on_time} layout="vertical" margin={{ left: 8, right: 16 }}>
                  <XAxis type="number" domain={[0, 100]} {...axisProps(c)} />
                  <YAxis type="category" dataKey="supplier" width={130} {...axisProps(c)} tick={{ fill: c.muted, fontSize: 10 }} interval={0} />
                  <Tooltip {...tooltipStyle(c)} cursor={{ fill: c.grid, opacity: 0.4 }} formatter={(v: number) => [`${v}%`, t('suppliers.onTime')]} />
                  <Bar dataKey="on_time_pct" fill={c.series[2]} radius={[0, 4, 4, 0]} maxBarSize={12} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t('dash.latestAlerts')} actions={<Link to="/alerts" className="text-xs text-brand-700 hover:underline dark:text-brand-400">{t('dash.viewAll')}</Link>}>
          {d.alerts.length === 0 ? <EmptyState title={t('alerts.none')} /> : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {d.alerts.map((a) => (
                <li key={a.id} className="flex items-start gap-2 py-2 text-sm">
                  <Badge tone={a.severity === 'critical' ? 'red' : a.severity === 'warning' ? 'amber' : 'blue'}>{t(`alertType.${a.type}`)}</Badge>
                  <span className="line-clamp-2 flex-1">{a.message}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title={t('dash.pendingList')} actions={<Link to="/approvals" className="text-xs text-brand-700 hover:underline dark:text-brand-400">{t('dash.viewAll')}</Link>}>
          {d.approvals.length === 0 ? <EmptyState title={t('approvals.nothingMine')} /> : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {d.approvals.map((p) => (
                <li key={p.id}>
                  <Link to={`/approvals?pr=${p.id}`} className="flex items-center gap-2 py-2 text-sm hover:bg-slate-50 dark:hover:bg-slate-800">
                    {p.created_by === 'agent' && <Bot className="h-4 w-4 shrink-0 text-violet-600" />}
                    <span className="flex-1 truncate">#{p.id} {p.product} · {formatNum(p.qty)} {p.unit}</span>
                    <span className="font-medium">{formatINR(p.est_total, false)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function StaffDashboard({ d }: { d: StaffData }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={t('dash.toReceive')} value={d.summary.to_receive} />
        <Stat label={t('dash.countsOpen')} value={d.summary.counts} />
        <Stat label={t('dash.expiringToMove')} value={d.summary.expiring} tone={d.summary.expiring ? 'red' : 'green'} />
        <Stat label={t('dash.outOfStock')} value={d.summary.out_of_stock} tone={d.summary.out_of_stock ? 'amber' : undefined} />
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Button className="h-16 text-base" icon={<ScanLine className="h-5 w-5" />} onClick={() => navigate('/sales')}>{t('dash.scanSell')}</Button>
        <Button className="h-16 text-base" variant="secondary" icon={<ScanLine className="h-5 w-5" />} onClick={() => navigate('/stock?tab=in')}>{t('dash.scanReceive')}</Button>
        <Button className="h-16 text-base" variant="secondary" icon={<PackageCheck className="h-5 w-5" />} onClick={() => navigate('/stock?tab=counts')}>{t('counts.title')}</Button>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t('dash.grnToday')}>
          {d.receive.length === 0 ? <EmptyState title={t('dash.nothingToReceive')} /> : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {d.receive.map((p) => (
                <li key={p.id}><Link to={`/orders/${p.id}`} className="flex items-center justify-between py-2 text-sm hover:underline">
                  <span>{p.po_no} · {p.supplier}</span><span className="text-xs text-slate-500">{t('orders.eta')} {formatDate(p.eta)}</span></Link></li>
              ))}
            </ul>
          )}
        </Card>
        <Card title={t('dash.moveExpiring')} actions={<Link to="/expiry" className="text-xs text-brand-700 hover:underline dark:text-brand-400">{t('dash.viewAll')}</Link>}>
          {d.expiring.length === 0 ? <EmptyState title={t('expiry.none')} /> : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {d.expiring.map((e) => (
                <li key={e.batch_id} className="py-2 text-sm"><p className="font-medium">{e.product} · {e.batch_no} · {formatNum(e.qty)} {e.unit}</p>
                  <p className="text-xs text-violet-700 dark:text-violet-300">{e.suggestion}</p></li>
              ))}
            </ul>
          )}
        </Card>
        {d.counts.length > 0 && (
          <Card title={t('dash.countsOpen')}>
            <ul className="text-sm">{d.counts.map((c) => <li key={c.id}>#{c.id} · {c.location} · {c.counted}/{c.lines}</li>)}</ul>
          </Card>
        )}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const q = useQuery({ queryKey: ['dashboard'], queryFn: () => api.get<{ role: string } & Partial<Mgmt> & { staff?: StaffData }>('/dashboard'),
    refetchInterval: 120_000, enabled: user?.role !== 'supplier' });
  if (user?.role === 'supplier') return <PortalHome />;
  return (
    <div>
      <PageHeader title={t('nav.dashboard')} subtitle={t('dash.greeting', { name: user?.name ?? '', when: formatDateTime(new Date()) })} />
      {q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !q.data ? <SkeletonRows rows={10} /> :
        q.data.role === 'staff' && q.data.staff ? <StaffDashboard d={q.data.staff} /> : <ManagementDashboard d={q.data as Mgmt} />}
    </div>
  );
}
