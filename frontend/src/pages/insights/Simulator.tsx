import { useMutation } from '@tanstack/react-query';
import { FlaskConical } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge, Button, Card, DataTable, EmptyState, Input, PageHeader, Select, Stat } from '@/components/ui';
import { useCategories, useSupplierOptions } from '@/hooks/useMasters';
import { api } from '@/lib/api';
import { formatINR, formatNum } from '@/lib/format';
import { useToast } from '@/lib/toast';

interface Calc {
  rop: number;
  ss: number;
  eoq: number;
  order_qty: number;
  lead_days?: number;
}
interface Row {
  product_id: number;
  product: string;
  unit: string;
  supplier: string | null;
  supplier_changed: boolean;
  no_supplier: boolean;
  current: Calc;
  new: Calc;
  cover_days: number | null;
  stockout_risk: boolean;
  cost: { purchase: number; holding: number; ordering: number };
}
interface Result {
  totals: { order_value: number; holding_cost: number; ordering_cost: number; stockout_risk: number; reorder_now: number; ss_change: number };
  products: Row[];
}

function Delta({ a, b }: { a: number; b: number }) {
  const d = b - a;
  return (
    <span className="tabular-nums">
      {formatNum(b)}
      {Math.abs(d) >= 0.05 && <span className={d > 0 ? 'ml-1 text-xs text-amber-600' : 'ml-1 text-xs text-emerald-600'}>({d > 0 ? '+' : ''}{formatNum(d)})</span>}
    </span>
  );
}

export default function Simulator() {
  const { t } = useTranslation();
  const toast = useToast();
  const cats = useCategories();
  const sups = useSupplierOptions();
  const [f, setF] = useState({ demand: '0', lead: '0', supplier: '', service: '0.95', category: '' });
  const [onlyChanged, setOnlyChanged] = useState(false);
  const run = useMutation({
    mutationFn: () => api.post<Result>('/simulator', {
      demand_change_pct: Number(f.demand), lead_time_change_days: Number(f.lead), unavailable_supplier_id: f.supplier ? Number(f.supplier) : null,
      service_level: Number(f.service), category_id: f.category ? Number(f.category) : null,
    }),
    onError: (e) => toast.error(e),
  });
  const r = run.data;
  const rows = r ? r.products.filter((p) => !onlyChanged || p.stockout_risk || p.supplier_changed || p.new.order_qty !== p.current.order_qty) : [];
  return (
    <div className="space-y-4">
      <PageHeader title={t('nav.simulator')} subtitle={t('sim.subtitle')} />
      <Card title={t('sim.assumptions')}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Input label={t('sim.demand')} type="number" value={f.demand} onChange={(e) => setF({ ...f, demand: e.target.value })} hint="−90 … +500" />
          <Input label={t('sim.lead')} type="number" value={f.lead} onChange={(e) => setF({ ...f, lead: e.target.value })} />
          <Select label={t('sim.unavailable')} value={f.supplier} onChange={(e) => setF({ ...f, supplier: e.target.value })} placeholder={t('sim.none')}
            options={(sups.data ?? []).map((s) => ({ value: s.id, label: s.name }))} />
          <Select label={t('settings.serviceLevel')} value={f.service} onChange={(e) => setF({ ...f, service: e.target.value })}
            options={['0.90', '0.95', '0.97', '0.99'].map((v) => ({ value: v, label: `${Number(v) * 100}%` }))} />
          <Select label={t('products.category')} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} placeholder={t('products.allCategories')}
            options={(cats.data ?? []).map((c) => ({ value: c.id, label: c.name }))} />
        </div>
        <div className="mt-3 flex items-center gap-3">
          <Button icon={<FlaskConical className="h-4 w-4" />} loading={run.isPending} onClick={() => run.mutate()}>{t('sim.run')}</Button>
          <span className="text-xs text-slate-500">{t('sim.noSave')}</span>
        </div>
      </Card>
      {!r ? <EmptyState title={t('sim.empty')} /> : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat label={t('sim.orderValue')} value={formatINR(r.totals.order_value, false)} />
            <Stat label={t('sim.holding')} value={formatINR(r.totals.holding_cost, false)} hint={t('sim.horizon')} />
            <Stat label={t('sim.ordering')} value={formatINR(r.totals.ordering_cost, false)} hint={t('sim.horizon')} />
            <Stat label={t('sim.reorderNow')} value={r.totals.reorder_now} />
            <Stat label={t('sim.stockoutRisk')} value={r.totals.stockout_risk} tone={r.totals.stockout_risk ? 'red' : 'green'} />
          </div>
          <Card title={t('sim.results')} actions={<label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} />{t('sim.onlyChanged')}</label>}>
            <DataTable<Row> rows={rows} rowKey={(x) => x.product_id}
              columns={[
                { key: 'product', header: t('common.product'), render: (x) => <div className="whitespace-normal"><p className="font-medium">{x.product}</p><p className="text-xs text-slate-500">{x.supplier ?? '—'}{x.supplier_changed && <Badge tone="purple" className="ml-1">{t('sim.switched')}</Badge>}</p></div> },
                { key: 'ss', header: 'SS', align: 'right', render: (x) => <Delta a={x.current.ss} b={x.new.ss} /> },
                { key: 'rop', header: 'ROP', align: 'right', render: (x) => <Delta a={x.current.rop} b={x.new.rop} /> },
                { key: 'eoq', header: 'EOQ', align: 'right', render: (x) => <Delta a={x.current.eoq} b={x.new.eoq} /> },
                { key: 'qty', header: t('sim.orderQty'), align: 'right', render: (x) => <Delta a={x.current.order_qty} b={x.new.order_qty} /> },
                { key: 'cover', header: t('sim.cover'), align: 'right', render: (x) => (x.cover_days == null ? '—' : `${formatNum(x.cover_days)} d`) },
                { key: 'cost', header: t('sim.purchase'), align: 'right', render: (x) => formatINR(x.cost.purchase, false) },
                { key: 'risk', header: t('sim.risk'), render: (x) => (x.no_supplier ? <Badge tone="red">{t('sim.noSupplier')}</Badge> : x.stockout_risk ? <Badge tone="red">{t('sim.stockout')}</Badge> : <Badge tone="green">OK</Badge>) },
              ]} />
          </Card>
        </>
      )}
    </div>
  );
}
