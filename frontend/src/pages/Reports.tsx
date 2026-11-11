import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CalendarClock, FileDown, FileSpreadsheet, Send, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge, Button, Card, DataTable, ErrorState, Input, Modal, PageHeader, Select, SkeletonRows, Stat, Tabs, type Column } from '@/components/ui';
import { useLocations } from '@/hooks/useMasters';
import { api } from '@/lib/api';
import { daysFromNow, formatDate, formatDateTime, formatINR, formatNum, isoDate } from '@/lib/format';
import { useToast } from '@/lib/toast';

interface Col {
  key: string;
  label: string;
  kind: 'text' | 'int' | 'qty' | 'money' | 'pct' | 'date';
}
interface ReportData {
  name: string;
  title: string;
  columns: Col[];
  rows: Record<string, unknown>[];
  totals: Record<string, number>;
  summary: { label: string; value: string }[];
}
interface Schedule {
  id: number;
  report: string;
  frequency: string;
  recipients: string[];
  fmt: string;
  is_active: boolean;
  last_sent_at: string | null;
}

const NAMES = ['stock_valuation', 'sales', 'purchases', 'supplier_performance', 'expiry_wastage', 'gst_summary'] as const;
type Name = (typeof NAMES)[number];

function cell(v: unknown, kind: Col['kind']): string {
  if (v === null || v === undefined || v === '') return '—';
  if (kind === 'money') return formatINR(Number(v));
  if (kind === 'pct') return `${Number(v).toFixed(1)}%`;
  if (kind === 'qty' || kind === 'int') return formatNum(Number(v));
  if (kind === 'date') return formatDate(String(v));
  return String(v);
}

function Schedules() {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ report: 'sales', frequency: 'weekly', recipients: '', fmt: 'both' });
  const q = useQuery({ queryKey: ['schedules'], queryFn: () => api.get<Schedule[]>('/report-schedules') });
  const refresh = () => void qc.invalidateQueries({ queryKey: ['schedules'] });
  const create = useMutation({
    mutationFn: () => api.post('/report-schedules', { ...f, recipients: f.recipients.split(/[,\s]+/).filter(Boolean) }),
    onSuccess: () => { setOpen(false); refresh(); toast.success(t('common.saved')); },
    onError: (e) => toast.error(e),
  });
  const send = useMutation({ mutationFn: (id: number) => api.post<{ sent: number }>(`/report-schedules/${id}/send`),
    onSuccess: (r) => { toast.success(t('reports.sentNow', { n: r.sent })); refresh(); }, onError: (e) => toast.error(e) });
  const del = useMutation({ mutationFn: (id: number) => api.del(`/report-schedules/${id}`), onSuccess: refresh, onError: (e) => toast.error(e) });
  return (
    <Card title={t('reports.schedules')} actions={<Button size="sm" icon={<CalendarClock className="h-4 w-4" />} onClick={() => setOpen(true)}>{t('reports.newSchedule')}</Button>}>
      <p className="mb-2 text-xs text-slate-500">{t('reports.schedulesHint')}</p>
      <DataTable<Schedule> rows={q.data} loading={q.isLoading} error={q.error} rowKey={(s) => s.id} empty={t('reports.noSchedules')}
        columns={[
          { key: 'report', header: t('reports.report'), render: (s) => t(`reports.${s.report}`) },
          { key: 'frequency', header: t('reports.frequency'), render: (s) => t(`reports.freq_${s.frequency}`) },
          { key: 'recipients', header: t('reports.recipients'), render: (s) => <span className="whitespace-normal text-xs">{s.recipients.join(', ')}</span> },
          { key: 'fmt', header: t('reports.format'), render: (s) => s.fmt.toUpperCase() },
          { key: 'last_sent_at', header: t('reports.lastSent'), render: (s) => formatDateTime(s.last_sent_at) },
          { key: 'a', header: '', render: (s) => <div className="flex gap-1"><Button size="sm" variant="secondary" icon={<Send className="h-3.5 w-3.5" />} loading={send.isPending} onClick={() => send.mutate(s.id)}>{t('reports.sendNow')}</Button>
            <Button size="sm" variant="ghost" aria-label={t('common.delete')} onClick={() => del.mutate(s.id)}><Trash2 className="h-4 w-4 text-rose-600" /></Button></div> },
        ]} />
      <Modal open={open} onClose={() => setOpen(false)} title={t('reports.newSchedule')}
        footer={<Button loading={create.isPending} disabled={!f.recipients.trim()} onClick={() => create.mutate()}>{t('common.save')}</Button>}>
        <div className="grid gap-3">
          <Select label={t('reports.report')} value={f.report} onChange={(e) => setF({ ...f, report: e.target.value })} options={NAMES.map((n) => ({ value: n, label: t(`reports.${n}`) }))} />
          <Select label={t('reports.frequency')} value={f.frequency} onChange={(e) => setF({ ...f, frequency: e.target.value })}
            options={['daily', 'weekly', 'monthly'].map((x) => ({ value: x, label: t(`reports.freq_${x}`) }))} />
          <Select label={t('reports.format')} value={f.fmt} onChange={(e) => setF({ ...f, fmt: e.target.value })} options={[{ value: 'pdf', label: 'PDF' }, { value: 'xlsx', label: 'Excel' }, { value: 'both', label: 'PDF + Excel' }]} />
          <Input label={t('reports.recipients')} value={f.recipients} onChange={(e) => setF({ ...f, recipients: e.target.value })} hint={t('reports.recipientsHint')} />
        </div>
      </Modal>
    </Card>
  );
}

export default function Reports() {
  const { t } = useTranslation();
  const toast = useToast();
  const locs = useLocations();
  const [name, setName] = useState<Name>('sales');
  const [from, setFrom] = useState(daysFromNow(-29));
  const [to, setTo] = useState(isoDate());
  const [loc, setLoc] = useState('');
  const params = { date_from: from, date_to: to, location_id: loc };
  const q = useQuery({ queryKey: ['report', name, params], queryFn: () => api.get<ReportData>(`/reports/${name}`, params) });
  const dl = (fmt: 'pdf' | 'xlsx') => api.download(`/reports/${name}`, `${name}_${to}.${fmt}`, { ...params, fmt }).catch(toast.error);
  const cols: Column<Record<string, unknown>>[] = (q.data?.columns ?? []).map((c) => ({
    key: c.key, header: c.label, align: ['money', 'qty', 'int', 'pct'].includes(c.kind) ? 'right' : 'left',
    render: (r) => <span className={c.kind === 'text' ? 'whitespace-normal' : ''}>{cell(r[c.key], c.kind)}</span>,
  }));
  return (
    <div className="space-y-4">
      <PageHeader title={t('nav.reports')} subtitle={t('reports.subtitle')} />
      <Tabs<Name> value={name} onChange={setName} tabs={NAMES.map((n) => ({ value: n, label: t(`reports.${n}`) }))} />
      <Card>
        <div className="flex flex-wrap items-end gap-2">
          {name !== 'stock_valuation' && <>
            <Input type="date" label={t('common.from')} value={from} onChange={(e) => setFrom(e.target.value)} />
            <Input type="date" label={t('common.to')} value={to} onChange={(e) => setTo(e.target.value)} />
          </>}
          {['stock_valuation', 'sales', 'purchases', 'expiry_wastage'].includes(name) && (
            <Select label={t('stock.location')} value={loc} onChange={(e) => setLoc(e.target.value)} placeholder={t('stock.allLocations')}
              options={(locs.data ?? []).map((l) => ({ value: l.id, label: l.name }))} />
          )}
          <div className="flex-1" />
          <Button variant="secondary" icon={<FileDown className="h-4 w-4" />} onClick={() => dl('pdf')}>PDF</Button>
          <Button variant="secondary" icon={<FileSpreadsheet className="h-4 w-4" />} onClick={() => dl('xlsx')}>Excel</Button>
        </div>
      </Card>
      {q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !q.data ? <SkeletonRows rows={8} /> : (
        <>
          {q.data.summary.length > 0 && (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3">{q.data.summary.map((s) => <Stat key={s.label} label={s.label} value={s.value} />)}</div>
          )}
          <Card title={q.data.title} actions={<Badge>{q.data.rows.length} {t('imports.rows')}</Badge>}>
            <DataTable rows={q.data.rows.map((r, i) => ({ ...r, __row: i }))} rowKey={(r) => r.__row as number} columns={cols} empty={t('reports.noData')} />
            {Object.keys(q.data.totals).length > 0 && (
              <div className="mt-3 flex flex-wrap justify-end gap-x-6 gap-y-1 border-t border-slate-200 pt-2 text-sm dark:border-slate-700">
                {q.data.columns.filter((c) => c.key in q.data.totals).map((c) => (
                  <span key={c.key}>{c.label}: <b>{cell(q.data.totals[c.key], c.kind)}</b></span>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
      <Schedules />
    </div>
  );
}
