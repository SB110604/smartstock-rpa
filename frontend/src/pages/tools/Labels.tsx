import { useQuery } from '@tanstack/react-query';
import { Printer } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { Batch, ProductRow } from '@/api/types';
import { Button, Card, DataTable, Input, PageHeader, Pagination, SearchBox, Tabs } from '@/components/ui';
import { api, type Page } from '@/lib/api';
import { formatDate, formatINR, formatNum } from '@/lib/format';
import { useToast } from '@/lib/toast';

export default function Labels() {
  const { t } = useTranslation();
  const toast = useToast();
  const [tab, setTab] = useState<'products' | 'batches'>('products');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [copies, setCopies] = useState(1);
  const [selected, setSelected] = useState<Set<string | number>>(new Set());
  const [busy, setBusy] = useState(false);
  const products = useQuery({
    queryKey: ['products', 'labels', q, page],
    queryFn: () => api.get<Page<ProductRow>>('/products', { q, page, page_size: 25 }),
    enabled: tab === 'products',
  });
  const batches = useQuery({
    queryKey: ['stock', 'batches', 'labels', q, page],
    queryFn: () => api.get<Page<Batch>>('/stock/batches', { q, page, page_size: 25 }),
    enabled: tab === 'batches',
  });
  const print = async () => {
    setBusy(true);
    try {
      const ids = [...selected].map(Number);
      await api.open(
        tab === 'products' ? '/labels/products' : '/labels/batches',
        undefined,
        tab === 'products' ? { product_ids: ids, copies } : { batch_ids: ids, copies },
      );
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };
  const switchTab = (v: 'products' | 'batches') => {
    setTab(v);
    setSelected(new Set());
    setPage(1);
  };
  return (
    <div>
      <PageHeader title={t('nav.labels')} subtitle={t('labels.subtitle')} />
      <Tabs
        tabs={[
          { value: 'products', label: t('nav.products') },
          { value: 'batches', label: t('products.batches') },
        ]}
        value={tab}
        onChange={switchTab}
      />
      <Card
        actions={
          <>
            <Input
              className="w-24"
              type="number"
              min={1}
              max={48}
              value={copies}
              onChange={(e) => setCopies(Math.max(1, Number(e.target.value)))}
              aria-label={t('labels.copies')}
            />
            <Button
              icon={<Printer className="h-4 w-4" />}
              disabled={!selected.size}
              loading={busy}
              onClick={print}
            >
              {t('labels.print', { n: selected.size })}
            </Button>
          </>
        }
        title={
          <SearchBox
            value={q}
            onChange={(v) => {
              setQ(v);
              setPage(1);
            }}
          />
        }
      >
        {tab === 'products' ? (
          <>
            <DataTable<ProductRow>
              rows={products.data?.items}
              loading={products.isLoading}
              error={products.error}
              rowKey={(p) => p.id}
              selectable
              selected={selected}
              onSelect={setSelected}
              columns={[
                { key: 'sku', header: t('products.sku'), className: 'font-mono text-xs' },
                { key: 'name', header: t('common.name') },
                { key: 'barcode', header: t('products.barcode'), render: (p) => p.barcode ?? '—' },
                {
                  key: 'selling_price',
                  header: t('products.price'),
                  align: 'right',
                  render: (p) => formatINR(p.selling_price),
                },
              ]}
            />
            {products.data && (
              <Pagination page={page} pageSize={25} total={products.data.total} onPage={setPage} />
            )}
          </>
        ) : (
          <>
            <DataTable<Batch>
              rows={batches.data?.items}
              loading={batches.isLoading}
              error={batches.error}
              rowKey={(b) => b.id}
              selectable
              selected={selected}
              onSelect={setSelected}
              columns={[
                { key: 'product_name', header: t('common.product') },
                { key: 'batch_no', header: t('stock.batch') },
                { key: 'location_name', header: t('stock.location') },
                { key: 'expiry_date', header: t('stock.expiry'), render: (b) => formatDate(b.expiry_date) },
                {
                  key: 'qty_on_hand',
                  header: t('common.qty'),
                  align: 'right',
                  render: (b) => formatNum(b.qty_on_hand),
                },
              ]}
            />
            {batches.data && (
              <Pagination page={page} pageSize={25} total={batches.data.total} onPage={setPage} />
            )}
          </>
        )}
      </Card>
    </div>
  );
}
