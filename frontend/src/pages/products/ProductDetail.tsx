import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Pencil } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import type { Batch, Movement, Position, Product, SupplierPrice } from '@/api/types';
import {
  Badge,
  Button,
  Card,
  DataTable,
  ErrorState,
  KeyValue,
  PageHeader,
  SkeletonRows,
  Stat,
  Tabs,
} from '@/components/ui';
import { ForecastChart } from '@/components/ForecastChart';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { formatDate, formatDateTime, formatINR, formatNum, titleCase } from '@/lib/format';
import ProductForm from './ProductForm';
import { StockStatusBadge } from './Products';

export interface ProductDetailData {
  product: Product;
  position: Position;
  stock_status: 'ok' | 'low' | 'out';
  by_location: (Position & { location_id: number; location: string })[];
  batches: Batch[];
  movements: Movement[];
  suppliers: SupplierPrice[];
  calc: Record<string, number | string | null> | null;
}

type Tab = 'overview' | 'batches' | 'movements' | 'suppliers' | 'forecast';


export default function ProductDetail() {
  const { id } = useParams();
  const { t } = useTranslation();
  const { can } = useAuth();
  const [tab, setTab] = useState<Tab>('overview');
  const [edit, setEdit] = useState(false);
  const q = useQuery({
    queryKey: ['products', 'detail', id],
    queryFn: () => api.get<ProductDetailData>(`/products/${id}`),
  });
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <SkeletonRows rows={8} />;
  const { product: p, position, by_location, batches, movements, suppliers, calc } = q.data;

  return (
    <div>
      <Link
        to="/products"
        className="mb-2 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700"
      >
        <ArrowLeft className="h-4 w-4" /> {t('nav.products')}
      </Link>
      <PageHeader
        title={p.name}
        subtitle={`${p.sku}${p.barcode ? ` · ${p.barcode}` : ''} · ${p.category_name ?? '—'}`}
        actions={
          <>
            <StockStatusBadge s={q.data.stock_status} />
            {!p.is_active && <Badge>{t('products.inactive')}</Badge>}
            {can('products.write') && (
              <Button variant="secondary" icon={<Pencil className="h-4 w-4" />} onClick={() => setEdit(true)}>
                {t('common.edit')}
              </Button>
            )}
          </>
        }
      />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={t('products.onHand')} value={`${formatNum(position.on_hand)} ${p.unit}`} />
        <Stat label={t('products.onOrder')} value={formatNum(position.on_order)} />
        <Stat
          label={t('products.rop')}
          value={formatNum(p.reorder_point)}
          hint={`SS ${formatNum(p.safety_stock)}`}
        />
        <Stat label="EOQ" value={formatNum(p.eoq)} hint={`${t('products.pack')} ${formatNum(p.pack_size)}`} />
      </div>
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { value: 'overview', label: t('products.overview') },
          { value: 'batches', label: t('products.batches'), count: batches.length },
          { value: 'movements', label: t('products.movements') },
          { value: 'suppliers', label: t('nav.suppliers'), count: suppliers.length },
          { value: 'forecast', label: t('insights.forecast') },
        ]}
      />
      {tab === 'overview' && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title={t('products.details')}>
            <KeyValue
              items={[
                [t('products.price'), formatINR(p.selling_price)],
                [t('products.cost'), formatINR(p.cost_price)],
                [t('products.gst'), `${p.gst_rate}%`],
                [t('products.hsn'), p.hsn_code ?? '—'],
                [t('products.unit'), p.unit],
                [t('products.moq'), formatNum(p.min_order_qty)],
                [
                  t('products.perishable'),
                  p.is_perishable ? `${t('common.yes')} (${p.shelf_life_days} d)` : t('common.no'),
                ],
                ['ABC / XYZ', p.abc_class ? `${p.abc_class} / ${p.xyz_class ?? '—'}` : '—'],
              ]}
            />
          </Card>
          <Card title={t('products.byLocation')}>
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="th">{t('stock.location')}</th>
                  <th className="th text-right">{t('products.onHand')}</th>
                  <th className="th text-right">{t('products.onOrder')}</th>
                  <th className="th text-right">{t('products.available')}</th>
                </tr>
              </thead>
              <tbody>
                {by_location.map((l) => (
                  <tr key={l.location_id}>
                    <td className="td">{l.location}</td>
                    <td className="td text-right">{formatNum(l.on_hand)}</td>
                    <td className="td text-right">{formatNum(l.on_order)}</td>
                    <td className="td text-right">{formatNum(l.available)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          <Card title={t('products.howComputed')} className="lg:col-span-2">
            {calc ? (
              <div className="space-y-2 text-sm">
                <KeyValue
                  items={Object.entries(calc)
                    .filter(([k]) => k !== 'explanation')
                    .map(([k, v]) => [titleCase(k), typeof v === 'number' ? formatNum(v) : String(v ?? '—')])}
                />
                {calc.explanation && (
                  <p className="rounded-md bg-slate-50 p-3 text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                    {calc.explanation}
                  </p>
                )}
              </div>
            ) : (
              <p className="text-sm text-slate-500">{t('products.notComputed')}</p>
            )}
          </Card>
        </div>
      )}
      {tab === 'batches' && (
        <Card>
          <DataTable<Batch>
            rows={batches}
            rowKey={(b) => b.id}
            empty={t('products.noBatches')}
            columns={[
              { key: 'batch_no', header: t('stock.batch') },
              { key: 'location_name', header: t('stock.location') },
              { key: 'expiry_date', header: t('stock.expiry'), render: (b) => formatDate(b.expiry_date) },
              {
                key: 'days_to_expiry',
                header: t('stock.daysLeft'),
                align: 'right',
                render: (b) => b.days_to_expiry ?? '—',
              },
              {
                key: 'qty_on_hand',
                header: t('common.qty'),
                align: 'right',
                render: (b) => formatNum(b.qty_on_hand),
              },
              {
                key: 'cost_price',
                header: t('products.cost'),
                align: 'right',
                render: (b) => formatINR(b.cost_price),
              },
              {
                key: 'markdown_pct',
                header: t('stock.markdown'),
                align: 'right',
                render: (b) => (b.markdown_pct ? `${b.markdown_pct}%` : '—'),
              },
              {
                key: 'is_blocked',
                header: t('common.status'),
                render: (b) =>
                  b.is_blocked ? (
                    <Badge tone="red">{t('stock.blocked')}</Badge>
                  ) : (
                    <Badge tone="green">OK</Badge>
                  ),
              },
            ]}
          />
        </Card>
      )}
      {tab === 'movements' && (
        <Card>
          <DataTable<Movement>
            rows={movements}
            rowKey={(m) => m.id}
            columns={[
              { key: 'created_at', header: t('common.date'), render: (m) => formatDateTime(m.created_at) },
              {
                key: 'type',
                header: t('stock.type'),
                render: (m) => t(`movement.${m.type}`, { defaultValue: m.type }),
              },
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
                key: 'reference_type',
                header: t('stock.reference'),
                render: (m) =>
                  m.reference_type
                    ? `${titleCase(m.reference_type)}${m.reference_id ? ` #${m.reference_id}` : ''}`
                    : '—',
              },
              {
                key: 'note',
                header: t('common.notes'),
                render: (m) => <span className="whitespace-normal text-xs">{m.note ?? '—'}</span>,
              },
            ]}
          />
        </Card>
      )}
      {tab === 'suppliers' && (
        <Card>
          <DataTable<SupplierPrice>
            rows={suppliers}
            rowKey={(s) => s.id}
            empty={t('products.noSuppliers')}
            columns={[
              {
                key: 'supplier_name',
                header: t('common.supplier'),
                render: (s) => (
                  <Link
                    className="text-brand-700 hover:underline dark:text-brand-400"
                    to={`/suppliers/${s.supplier_id}`}
                  >
                    {s.supplier_name}
                  </Link>
                ),
              },
              {
                key: 'unit_price',
                header: t('suppliers.unitPrice'),
                align: 'right',
                render: (s) => formatINR(s.unit_price),
              },
              {
                key: 'lead_time_days',
                header: t('suppliers.leadTime'),
                align: 'right',
                render: (s) => `${s.lead_time_days} d`,
              },
              {
                key: 'min_order_qty',
                header: t('products.moq'),
                align: 'right',
                render: (s) => formatNum(s.min_order_qty),
              },
              {
                key: 'valid_till',
                header: t('suppliers.validTill'),
                render: (s) => formatDate(s.valid_till),
              },
            ]}
          />
        </Card>
      )}
      {tab === 'forecast' && (
        <Card title={t('insights.forecastTitle')}>
          <ForecastChart productId={p.id} unit={p.unit} />
        </Card>
      )}
      <ProductForm product={p} open={edit} onClose={() => setEdit(false)} />
    </div>
  );
}
