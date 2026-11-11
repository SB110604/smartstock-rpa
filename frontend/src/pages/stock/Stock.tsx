import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import type { Movement } from '@/api/types';
import { Card, DataTable, PageHeader, Pagination, Select, Tabs } from '@/components/ui';
import { useLocations } from '@/hooks/useMasters';
import { useCurrentLocation } from '@/hooks/useCurrentLocation';
import { api, type Page } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { formatDateTime, formatNum, titleCase } from '@/lib/format';
import Counts from './Counts';
import { Adjust, StockIn, StockOut } from './StockOps';
import Transfers from './Transfers';

type Tab = 'in' | 'out' | 'adjust' | 'transfers' | 'counts' | 'movements';

function Movements({ locationId }: { locationId?: number }) {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const [type, setType] = useState('');
  const q = useQuery({
    queryKey: ['stock', 'movements', locationId, type, page],
    queryFn: () =>
      api.get<Page<Movement>>('/stock/movements', { location_id: locationId, type, page, page_size: 30 }),
  });
  return (
    <Card
      title={t('products.movements')}
      actions={
        <Select
          value={type}
          onChange={(e) => {
            setType(e.target.value);
            setPage(1);
          }}
          placeholder={t('common.all')}
          aria-label={t('stock.type')}
          options={[
            'purchase_in',
            'sale_out',
            'adjustment',
            'transfer_in',
            'transfer_out',
            'return_out',
            'write_off',
          ].map((v) => ({ value: v, label: t(`movement.${v}`) }))}
        />
      }
    >
      <DataTable<Movement>
        rows={q.data?.items}
        loading={q.isLoading}
        error={q.error}
        rowKey={(m) => m.id}
        columns={[
          { key: 'created_at', header: t('common.date'), render: (m) => formatDateTime(m.created_at) },
          {
            key: 'product_name',
            header: t('common.product'),
            render: (m) => <span className="whitespace-normal">{m.product_name}</span>,
          },
          { key: 'batch_no', header: t('stock.batch') },
          { key: 'type', header: t('stock.type'), render: (m) => t(`movement.${m.type}`) },
          {
            key: 'qty',
            header: t('common.qty'),
            align: 'right',
            render: (m) => (
              <span className={m.qty < 0 ? 'text-rose-600' : 'text-emerald-600'}>
                {m.qty > 0 ? '+' : ''}
                {formatNum(m.qty)}
              </span>
            ),
          },
          {
            key: 'ref',
            header: t('stock.reference'),
            render: (m) => (m.reference_type ? titleCase(m.reference_type) : '—'),
          },
          { key: 'user_name', header: t('stock.by'), render: (m) => m.user_name ?? t('stock.system') },
        ]}
      />
      {q.data && <Pagination page={page} pageSize={30} total={q.data.total} onPage={setPage} />}
    </Card>
  );
}

export default function Stock() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const locs = useLocations();
  const [locationId, setLocationId] = useCurrentLocation();
  const [sp, setSp] = useSearchParams();
  const tab = (sp.get('tab') as Tab) ?? 'in';
  const tabs: { value: Tab; label: string }[] = [
    { value: 'in', label: t('stock.in') },
    { value: 'out', label: t('stock.out') },
    ...(can('stock.adjust') ? [{ value: 'adjust' as Tab, label: t('stock.adjust') }] : []),
    { value: 'transfers', label: t('nav.transfers') },
    { value: 'counts', label: t('counts.title') },
    { value: 'movements', label: t('products.movements') },
  ];
  return (
    <div>
      <PageHeader
        title={t('nav.stock')}
        subtitle={t('stock.subtitle')}
        actions={
          <Select
            value={locationId ?? ''}
            onChange={(e) => setLocationId(Number(e.target.value))}
            aria-label={t('stock.location')}
            options={(locs.data ?? []).map((l) => ({ value: l.id, label: l.name }))}
          />
        }
      />
      <Tabs<Tab> tabs={tabs} value={tab} onChange={(v) => setSp({ tab: v }, { replace: true })} />
      {tab === 'in' && <StockIn locationId={locationId} />}
      {tab === 'out' && <StockOut locationId={locationId} />}
      {tab === 'adjust' && <Adjust locationId={locationId} />}
      {tab === 'transfers' && <Transfers />}
      {tab === 'counts' && <Counts locationId={locationId} />}
      {tab === 'movements' && <Movements locationId={locationId} />}
    </div>
  );
}
