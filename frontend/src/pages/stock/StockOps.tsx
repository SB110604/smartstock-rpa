import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { Batch, Lookup } from '@/api/types';
import { ProductPicker } from '@/components/ProductPicker';
import { Badge, Button, Card, Input, Select, Textarea } from '@/components/ui';
import { useSupplierOptions } from '@/hooks/useMasters';
import { api, type Page } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { daysFromNow, formatDate, formatINR, formatNum } from '@/lib/format';
import { useToast } from '@/lib/toast';

function PickedProduct({ l }: { l: Lookup }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-lg border border-brand-200 bg-brand-50 p-3 text-sm dark:border-brand-800 dark:bg-brand-900/20">
      <p className="font-semibold">{l.product.name}</p>
      <p className="text-xs text-slate-600 dark:text-slate-300">
        {l.product.sku} · {formatINR(l.product.selling_price)} · {t('products.onHand')}:{' '}
        <b>
          {formatNum(l.stock.on_hand)} {l.product.unit}
        </b>
        {l.batch && (
          <>
            {' '}
            · {t('stock.batch')} {l.batch.batch_no}
          </>
        )}
      </p>
    </div>
  );
}

export function StockIn({ locationId }: { locationId?: number }) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const { can } = useAuth();
  const suppliers = useSupplierOptions(can('suppliers.read'));
  const [picked, setPicked] = useState<Lookup | null>(null);
  const [f, setF] = useState({
    qty: '',
    batch_no: '',
    expiry_date: '',
    cost_price: '',
    supplier_id: '',
    note: '',
  });
  const pick = (l: Lookup) => {
    setPicked(l);
    setF((v) => ({
      ...v,
      batch_no: l.batch?.batch_no ?? '',
      expiry_date:
        l.batch?.expiry_date ?? (l.product.shelf_life_days ? daysFromNow(l.product.shelf_life_days) : ''),
      cost_price: String(l.product.cost_price),
    }));
  };
  const save = useMutation({
    mutationFn: () =>
      api.post<Batch>('/stock/in', {
        product_id: picked!.product.id,
        location_id: locationId,
        qty: Number(f.qty),
        batch_no: f.batch_no || null,
        expiry_date: f.expiry_date || null,
        cost_price: f.cost_price === '' ? null : Number(f.cost_price),
        supplier_id: f.supplier_id ? Number(f.supplier_id) : null,
        note: f.note || null,
      }),
    onSuccess: (b) => {
      toast.success(t('stock.receivedOk', { qty: formatNum(b.qty_on_hand), batch: b.batch_no }));
      setPicked(null);
      setF({ qty: '', batch_no: '', expiry_date: '', cost_price: '', supplier_id: '', note: '' });
      void qc.invalidateQueries({ queryKey: ['products'] });
      void qc.invalidateQueries({ queryKey: ['stock'] });
    },
    onError: (e) => toast.error(e),
  });
  return (
    <Card title={t('stock.in')}>
      <div className="space-y-3">
        <ProductPicker onPick={pick} locationId={locationId} autoFocus />
        {picked && (
          <>
            <PickedProduct l={picked} />
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <Input
                label={`${t('common.qty')} (${picked.product.unit})`}
                type="number"
                step="0.001"
                min="0"
                value={f.qty}
                onChange={(e) => setF({ ...f, qty: e.target.value })}
                autoFocus
              />
              <Input
                label={t('stock.batch')}
                value={f.batch_no}
                onChange={(e) => setF({ ...f, batch_no: e.target.value })}
              />
              <Input
                label={t('stock.expiry')}
                type="date"
                value={f.expiry_date}
                onChange={(e) => setF({ ...f, expiry_date: e.target.value })}
                hint={picked.product.is_perishable ? t('stock.expiryRequired') : undefined}
              />
              <Input
                label={t('products.cost')}
                type="number"
                step="0.01"
                value={f.cost_price}
                onChange={(e) => setF({ ...f, cost_price: e.target.value })}
              />
              {can('suppliers.read') && (
                <Select
                  label={t('nav.suppliers')}
                  value={f.supplier_id}
                  onChange={(e) => setF({ ...f, supplier_id: e.target.value })}
                  placeholder="—"
                  options={(suppliers.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
                />
              )}
              <Input
                label={t('common.notes')}
                value={f.note}
                onChange={(e) => setF({ ...f, note: e.target.value })}
              />
            </div>
            <Button
              loading={save.isPending}
              disabled={!(Number(f.qty) > 0) || !locationId}
              onClick={() => save.mutate()}
            >
              {t('stock.receive')}
            </Button>
          </>
        )}
      </div>
    </Card>
  );
}

export function StockOut({ locationId }: { locationId?: number }) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const { can } = useAuth();
  const [picked, setPicked] = useState<Lookup | null>(null);
  const [f, setF] = useState({ qty: '', type: 'write_off', reason: '' });
  const [result, setResult] = useState<
    { batch_no: string; expiry_date: string | null; qty: number }[] | null
  >(null);
  const types = ['write_off', 'return_out', 'sale_out', ...(can('stock.adjust') ? ['adjustment'] : [])];
  const save = useMutation({
    mutationFn: () =>
      api.post<{ picked: { batch_no: string; expiry_date: string | null; qty: number }[] }>('/stock/out', {
        product_id: picked!.product.id,
        location_id: locationId,
        qty: Number(f.qty),
        type: f.type,
        reason: f.reason,
        batch_id: picked!.batch?.id ?? null,
      }),
    onSuccess: (r) => {
      toast.success(t('stock.issuedOk'));
      setResult(r.picked);
      setPicked(null);
      setF({ qty: '', type: f.type, reason: '' });
      void qc.invalidateQueries({ queryKey: ['products'] });
      void qc.invalidateQueries({ queryKey: ['stock'] });
    },
    onError: (e) => toast.error(e),
  });
  return (
    <Card title={t('stock.out')}>
      <div className="space-y-3">
        <p className="text-xs text-slate-500">{t('stock.fefoHint')}</p>
        <ProductPicker
          onPick={(l) => {
            setPicked(l);
            setResult(null);
          }}
          locationId={locationId}
        />
        {picked && (
          <>
            <PickedProduct l={picked} />
            <div className="grid grid-cols-2 gap-3">
              <Input
                label={t('common.qty')}
                type="number"
                step="0.001"
                value={f.qty}
                onChange={(e) => setF({ ...f, qty: e.target.value })}
                autoFocus
              />
              <Select
                label={t('stock.type')}
                value={f.type}
                onChange={(e) => setF({ ...f, type: e.target.value })}
                options={types.map((ty) => ({ value: ty, label: t(`movement.${ty}`) }))}
              />
              <Textarea
                className="col-span-2"
                label={t('common.reason')}
                value={f.reason}
                onChange={(e) => setF({ ...f, reason: e.target.value })}
              />
            </div>
            <Button
              variant="danger"
              loading={save.isPending}
              disabled={!(Number(f.qty) > 0) || f.reason.trim().length < 3 || !locationId}
              onClick={() => save.mutate()}
            >
              {t('stock.issue')}
            </Button>
          </>
        )}
        {result && (
          <div className="rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800">
            <p className="mb-1 font-medium">{t('stock.pickedBatches')}</p>
            <ul className="space-y-0.5 text-xs">
              {result.map((r) => (
                <li key={r.batch_no}>
                  {r.batch_no} · {t('stock.expiry')} {formatDate(r.expiry_date)} · {formatNum(r.qty)}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  );
}

export function Adjust({ locationId }: { locationId?: number }) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const [picked, setPicked] = useState<Lookup | null>(null);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [newQty, setNewQty] = useState('');
  const [reason, setReason] = useState('');
  const batches = useQuery({
    queryKey: ['stock', 'batches', picked?.product.id, locationId],
    queryFn: () =>
      api.get<Page<Batch>>('/stock/batches', {
        product_id: picked!.product.id,
        location_id: locationId,
        page_size: 100,
      }),
    enabled: !!picked,
  });
  const save = useMutation({
    mutationFn: () => api.post('/stock/adjust', { batch_id: batch!.id, new_qty: Number(newQty), reason }),
    onSuccess: () => {
      toast.success(t('common.saved'));
      setBatch(null);
      setNewQty('');
      setReason('');
      void qc.invalidateQueries({ queryKey: ['stock'] });
      void qc.invalidateQueries({ queryKey: ['products'] });
    },
    onError: (e) => toast.error(e),
  });
  return (
    <Card title={t('stock.adjust')}>
      <div className="space-y-3">
        <ProductPicker
          onPick={(l) => {
            setPicked(l);
            setBatch(null);
          }}
          locationId={locationId}
        />
        {picked && (
          <div className="space-y-2">
            {(batches.data?.items ?? []).map((b) => (
              <button
                key={b.id}
                type="button"
                onClick={() => {
                  setBatch(b);
                  setNewQty(String(b.qty_on_hand));
                }}
                className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left text-sm ${batch?.id === b.id ? 'border-brand-500 bg-brand-50 dark:bg-brand-900/20' : 'border-slate-200 dark:border-slate-700'}`}
              >
                <span>
                  {b.batch_no} · {t('stock.expiry')} {formatDate(b.expiry_date)}
                </span>
                <span className="flex items-center gap-2">
                  {b.is_blocked && <Badge tone="red">{t('stock.blocked')}</Badge>}
                  <b>{formatNum(b.qty_on_hand)}</b>
                </span>
              </button>
            ))}
            {batches.data?.items.length === 0 && (
              <p className="text-sm text-slate-500">{t('products.noBatches')}</p>
            )}
          </div>
        )}
        {batch && (
          <div className="grid grid-cols-2 gap-3">
            <Input
              label={t('stock.newQty')}
              type="number"
              step="0.001"
              min="0"
              value={newQty}
              onChange={(e) => setNewQty(e.target.value)}
            />
            <div className="flex items-end text-sm text-slate-500">
              {t('stock.delta')}: {formatNum(Number(newQty) - batch.qty_on_hand)}
            </div>
            <Textarea
              className="col-span-2"
              label={t('common.reason')}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <Button
              loading={save.isPending}
              disabled={reason.trim().length < 3 || newQty === ''}
              onClick={() => save.mutate()}
            >
              {t('common.save')}
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}
