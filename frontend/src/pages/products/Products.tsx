import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { ProductRow } from '@/api/types';
import {
  Badge,
  Button,
  Card,
  DataTable,
  PageHeader,
  Pagination,
  SearchBox,
  Select,
  type Column,
} from '@/components/ui';
import { useCategories, useLocations } from '@/hooks/useMasters';
import { api, type Page } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { formatINR, formatNum } from '@/lib/format';
import ProductForm from './ProductForm';

export function StockStatusBadge({ s }: { s: ProductRow['stock_status'] }) {
  const { t } = useTranslation();
  return (
    <Badge tone={s === 'out' ? 'red' : s === 'low' ? 'amber' : 'green'}>{t(`products.status_${s}`)}</Badge>
  );
}

export default function Products() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const [sp, setSp] = useSearchParams();
  const [form, setForm] = useState(false);
  const cats = useCategories();
  const locs = useLocations();
  const page = Number(sp.get('page') ?? 1);
  const params = {
    q: sp.get('q') ?? '',
    category_id: sp.get('category_id') ?? '',
    location_id: sp.get('location_id') ?? '',
    status: sp.get('status') ?? '',
    sort: sp.get('sort') ?? 'name',
    page,
    page_size: 25,
  };
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(sp);
    if (v) n.set(k, v);
    else n.delete(k);
    if (k !== 'page') n.delete('page');
    setSp(n, { replace: true });
  };
  const q = useQuery({
    queryKey: ['products', params],
    queryFn: () => api.get<Page<ProductRow>>('/products', params),
  });

  const columns: Column<ProductRow>[] = [
    { key: 'sku', header: t('products.sku'), sortable: true, className: 'font-mono text-xs' },
    {
      key: 'name',
      header: t('common.name'),
      sortable: true,
      render: (p) => (
        <div className="max-w-xs whitespace-normal">
          <p className="font-medium">{p.name}</p>
          <p className="text-xs text-slate-500">
            {p.category_name ?? '—'}
            {p.is_perishable && <span className="ml-1 text-amber-600">• {t('products.perishable')}</span>}
          </p>
        </div>
      ),
    },
    {
      key: 'selling_price',
      header: t('products.price'),
      sortable: true,
      align: 'right',
      render: (p) => formatINR(p.selling_price),
    },
    {
      key: 'on_hand',
      header: t('products.onHand'),
      sortable: true,
      align: 'right',
      render: (p) => `${formatNum(p.on_hand)} ${p.unit}`,
    },
    { key: 'on_order', header: t('products.onOrder'), align: 'right', render: (p) => formatNum(p.on_order) },
    {
      key: 'reorder_point',
      header: t('products.rop'),
      align: 'right',
      render: (p) => formatNum(p.reorder_point),
    },
    {
      key: 'abc_class',
      header: 'ABC/XYZ',
      sortable: true,
      render: (p) => (p.abc_class ? `${p.abc_class}${p.xyz_class ?? ''}` : '—'),
    },
    {
      key: 'stock_status',
      header: t('common.status'),
      render: (p) => <StockStatusBadge s={p.stock_status} />,
    },
  ];

  return (
    <div>
      <PageHeader
        title={t('nav.products')}
        subtitle={t('products.subtitle')}
        actions={
          can('products.write') && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => setForm(true)}>
              {t('products.new')}
            </Button>
          )
        }
      />
      <Card>
        <div className="mb-3 grid grid-cols-1 gap-2 sm:flex sm:flex-wrap">
          <SearchBox value={params.q} onChange={(v) => set('q', v)} placeholder={t('products.searchHint')} />
          <Select
            className="sm:w-44"
            value={params.category_id}
            onChange={(e) => set('category_id', e.target.value)}
            aria-label={t('products.category')}
            placeholder={t('products.allCategories')}
            options={(cats.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
          />
          <Select
            className="sm:w-44"
            value={params.location_id}
            onChange={(e) => set('location_id', e.target.value)}
            aria-label={t('stock.location')}
            placeholder={t('stock.allLocations')}
            options={(locs.data ?? []).map((l) => ({ value: l.id, label: l.name }))}
          />
          <Select
            className="sm:w-40"
            value={params.status}
            onChange={(e) => set('status', e.target.value)}
            aria-label={t('common.status')}
            placeholder={t('common.all')}
            options={['out', 'low', 'ok'].map((s) => ({ value: s, label: t(`products.status_${s}`) }))}
          />
        </div>
        <DataTable
          columns={columns}
          rows={q.data?.items}
          loading={q.isLoading}
          error={q.error}
          onRetry={() => q.refetch()}
          rowKey={(p) => p.id}
          sort={params.sort}
          onSort={(s) => set('sort', s)}
          onRowClick={(p) => navigate(`/products/${p.id}`)}
          empty={t('products.empty')}
        />
        {q.data && (
          <Pagination page={page} pageSize={25} total={q.data.total} onPage={(p) => set('page', String(p))} />
        )}
      </Card>
      <ProductForm open={form} onClose={() => setForm(false)} />
    </div>
  );
}
