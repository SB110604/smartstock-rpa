import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge, Card, DataTable, Input, Modal, PageHeader, Pagination, Select } from '@/components/ui';
import { api, type Page } from '@/lib/api';
import { formatDateTime } from '@/lib/format';

interface Entry {
  id: number;
  user_name: string | null;
  action: string;
  entity: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  ip: string | null;
  created_at: string;
}

const show = (v: unknown) =>
  v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v);

export function Diff({
  before,
  after,
}: {
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}) {
  const { t } = useTranslation();
  const keys = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])].sort();
  if (!keys.length) return <p className="text-sm text-slate-500">{t('audit.noChanges')}</p>;
  return (
    <table className="w-full text-xs">
      <thead>
        <tr>
          <th className="th">{t('audit.field')}</th>
          <th className="th">{t('audit.before')}</th>
          <th className="th">{t('audit.after')}</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
        {keys.map((k) => (
          <tr key={k}>
            <td className="td font-medium">{k}</td>
            <td className="td whitespace-normal break-all bg-rose-50/60 dark:bg-rose-900/10">
              {show(before?.[k])}
            </td>
            <td className="td whitespace-normal break-all bg-emerald-50/60 dark:bg-emerald-900/10">
              {show(after?.[k])}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Audit() {
  const { t } = useTranslation();
  const [f, setF] = useState({ entity: '', action: '', date_from: '', date_to: '' });
  const [page, setPage] = useState(1);
  const [view, setView] = useState<Entry | null>(null);
  const entities = useQuery({
    queryKey: ['audit', 'entities'],
    queryFn: () => api.get<string[]>('/audit/entities'),
  });
  const q = useQuery({
    queryKey: ['audit', f, page],
    queryFn: () => api.get<Page<Entry>>('/audit', { ...f, page, page_size: 50 }),
  });
  const set = (k: keyof typeof f, v: string) => {
    setF({ ...f, [k]: v });
    setPage(1);
  };
  return (
    <div>
      <PageHeader title={t('nav.audit')} subtitle={t('audit.subtitle')} />
      <Card>
        <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4">
          <Select
            value={f.entity}
            onChange={(e) => set('entity', e.target.value)}
            placeholder={t('audit.allEntities')}
            aria-label={t('audit.entity')}
            options={(entities.data ?? []).map((e) => ({ value: e, label: e }))}
          />
          <Select
            value={f.action}
            onChange={(e) => set('action', e.target.value)}
            placeholder={t('audit.allActions')}
            aria-label={t('audit.action')}
            options={[
              'create',
              'update',
              'delete',
              'transition',
              'login',
              'import',
              'write_off',
              'negative_stock_attempt',
            ].map((a) => ({ value: a, label: a }))}
          />
          <Input
            type="date"
            value={f.date_from}
            onChange={(e) => set('date_from', e.target.value)}
            aria-label={t('common.from')}
          />
          <Input
            type="date"
            value={f.date_to}
            onChange={(e) => set('date_to', e.target.value)}
            aria-label={t('common.to')}
          />
        </div>
        <DataTable<Entry>
          rows={q.data?.items}
          loading={q.isLoading}
          error={q.error}
          rowKey={(e) => e.id}
          onRowClick={setView}
          columns={[
            { key: 'created_at', header: t('common.date'), render: (e) => formatDateTime(e.created_at) },
            { key: 'user_name', header: t('audit.user'), render: (e) => e.user_name ?? t('stock.system') },
            {
              key: 'action',
              header: t('audit.action'),
              render: (e) => (
                <Badge tone={e.action === 'delete' ? 'red' : e.action === 'create' ? 'green' : 'blue'}>
                  {e.action}
                </Badge>
              ),
            },
            {
              key: 'entity',
              header: t('audit.entity'),
              render: (e) => `${e.entity}${e.entity_id ? ` #${e.entity_id}` : ''}`,
            },
            { key: 'ip', header: 'IP', render: (e) => e.ip ?? '—' },
          ]}
        />
        {q.data && <Pagination page={page} pageSize={50} total={q.data.total} onPage={setPage} />}
      </Card>
      <Modal
        open={!!view}
        onClose={() => setView(null)}
        wide
        title={view ? `${view.action} · ${view.entity} #${view.entity_id ?? ''}` : ''}
      >
        {view && <Diff before={view.before} after={view.after} />}
      </Modal>
    </div>
  );
}
