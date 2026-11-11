import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, FileDown, Mail, PackageCheck, Receipt, XCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { ScanButton, ScannerModal } from '@/components/Scanner';
import { Timeline, type TimelineItem } from '@/components/Timeline';
import { Badge, Button, Card, ErrorState, Input, KeyValue, Modal, PageHeader, SkeletonRows, StatusBadge, Textarea } from '@/components/ui';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { daysFromNow, formatDate, formatDateTime, formatINR, formatNum, isoDate } from '@/lib/format';
import { useToast } from '@/lib/toast';
import type { PORow } from './Orders';

export interface POLine {
  id: number;
  product_id: number;
  product: string;
  sku: string;
  unit: string;
  is_perishable: boolean;
  shelf_life_days: number | null;
  hsn_code: string | null;
  qty: number;
  unit_price: number;
  gst_rate: number;
  received_qty: number;
  damaged_qty: number;
  remaining: number;
}
interface MatchLine {
  product: string;
  po_qty: number;
  grn_qty: number;
  invoice_qty: number;
  po_price: number;
  invoice_price: number;
  price_diff_pct: number | null;
  status: string;
  note?: string;
}
export interface PODetail extends PORow {
  supplier_detail: { gstin: string | null; state: string; email: string | null; phone: string | null };
  lines: POLine[];
  timeline: TimelineItem[];
  grns: { id: number; grn_no: string; received_at: string; lines: { product: string; received_qty: number; damaged_qty: number; batch_no: string; expiry_date: string | null }[] }[];
  invoices: { id: number; invoice_no: string; invoice_date: string; total: number; status: string; source: string }[];
  matches: { id: number; status: string; details: { lines: MatchLine[]; tolerance: { qty_pct: number; price_pct: number } }; resolution_note: string | null }[];
  returns: { id: number; return_no: string; status: string; total: number }[];
}

export function LinesTable({ po }: { po: PODetail }) {
  const { t } = useTranslation();
  return (
    <div className="-mx-4 overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr>
            <th className="th">{t('nav.products')}</th><th className="th">HSN</th><th className="th text-right">{t('common.qty')}</th>
            <th className="th text-right">{t('orders.rate')}</th><th className="th text-right">GST</th>
            <th className="th text-right">{t('orders.received')}</th><th className="th text-right">{t('orders.damaged')}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {po.lines.map((l) => (
            <tr key={l.id}>
              <td className="td whitespace-normal"><p className="font-medium">{l.product}</p><p className="text-xs text-slate-500">{l.sku}</p></td>
              <td className="td">{l.hsn_code}</td>
              <td className="td text-right">{formatNum(l.qty)} {l.unit}</td>
              <td className="td text-right">{formatINR(l.unit_price)}</td>
              <td className="td text-right">{l.gst_rate}%</td>
              <td className="td text-right">{formatNum(l.received_qty)}</td>
              <td className="td text-right">{l.damaged_qty ? <span className="text-rose-600">{formatNum(l.damaged_qty)}</span> : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex justify-end px-4">
        <dl className="w-64 space-y-1 text-sm">
          <div className="flex justify-between"><dt>{t('sales.taxable')}</dt><dd>{formatINR(po.subtotal)}</dd></div>
          {po.is_interstate ? (
            <div className="flex justify-between"><dt>IGST</dt><dd>{formatINR(po.igst)}</dd></div>
          ) : (
            <>
              <div className="flex justify-between"><dt>CGST</dt><dd>{formatINR(po.cgst)}</dd></div>
              <div className="flex justify-between"><dt>SGST</dt><dd>{formatINR(po.sgst)}</dd></div>
            </>
          )}
          <div className="flex justify-between border-t pt-1 font-semibold dark:border-slate-700"><dt>{t('common.total')}</dt><dd>{formatINR(po.total)}</dd></div>
        </dl>
      </div>
    </div>
  );
}

function GrnForm({ po, open, onClose }: { po: PODetail; open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const [scan, setScan] = useState(false);
  const [note, setNote] = useState('');
  type Row = { received: string; damaged: string; batch: string; expiry: string };
  const [rows, setRows] = useState<Record<number, Row>>({});
  useEffect(() => {
    if (open)
      setRows(Object.fromEntries(po.lines.filter((l) => l.remaining > 0).map((l) => [l.id, {
        received: String(l.remaining), damaged: '0', batch: '', expiry: l.shelf_life_days ? daysFromNow(l.shelf_life_days) : '',
      }])));
  }, [open, po.lines]);
  const save = useMutation({
    mutationFn: () => api.post<{ grn_no: string }>(`/purchase-orders/${po.id}/grn`, {
      note: note || null,
      lines: Object.entries(rows).map(([id, r]) => ({
        po_line_id: Number(id), received_qty: Number(r.received) || 0, damaged_qty: Number(r.damaged) || 0,
        batch_no: r.batch || null, expiry_date: r.expiry || null,
      })),
    }),
    onSuccess: (r) => {
      toast.success(t('orders.grnDone', { no: r.grn_no }));
      void qc.invalidateQueries({ queryKey: ['po', String(po.id)] });
      void qc.invalidateQueries({ queryKey: ['orders'] });
      void qc.invalidateQueries({ queryKey: ['products'] });
      onClose();
    },
    onError: (e) => toast.error(e),
  });
  const onScan = (code: string) => {
    setScan(false);
    const [sku, batch] = code.split('|');
    const line = po.lines.find((l) => l.sku === sku || code.includes(l.sku));
    if (!line || !rows[line.id]) return toast.error(t('orders.notOnPo', { code }));
    if (batch) setRows((r) => ({ ...r, [line.id]: { ...r[line.id], batch } }));
    document.getElementById(`grn-${line.id}`)?.focus();
  };
  const set = (id: number, k: keyof Row, v: string) => setRows((r) => ({ ...r, [id]: { ...r[id], [k]: v } }));
  return (
    <Modal open={open} onClose={onClose} wide title={`${t('orders.receive')} — ${po.po_no}`}
      footer={<><ScanButton onClick={() => setScan(true)} /><Button loading={save.isPending} onClick={() => save.mutate()}>{t('orders.postGrn')}</Button></>}>
      <div className="space-y-3">
        {po.lines.filter((l) => rows[l.id]).map((l) => (
          <div key={l.id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
            <p className="text-sm font-medium">{l.product} <span className="text-xs text-slate-500">· {t('orders.remaining')} {formatNum(l.remaining)} {l.unit}</span></p>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Input id={`grn-${l.id}`} label={t('orders.received')} type="number" min="0" value={rows[l.id].received} onChange={(e) => set(l.id, 'received', e.target.value)} />
              <Input label={t('orders.damaged')} type="number" min="0" value={rows[l.id].damaged} onChange={(e) => set(l.id, 'damaged', e.target.value)} />
              <Input label={t('stock.batch')} value={rows[l.id].batch} onChange={(e) => set(l.id, 'batch', e.target.value)} />
              <Input label={t('stock.expiry')} type="date" value={rows[l.id].expiry} onChange={(e) => set(l.id, 'expiry', e.target.value)} />
            </div>
          </div>
        ))}
        <Textarea label={t('common.notes')} value={note} onChange={(e) => setNote(e.target.value)} />
        <p className="text-xs text-slate-500">{t('orders.damagedHint')}</p>
      </div>
      <ScannerModal open={scan} onClose={() => setScan(false)} onDetected={onScan} />
    </Modal>
  );
}

interface OcrResult {
  invoice_no: string | null;
  invoice_date: string | null;
  overall_confidence: number;
  lines: { po_line_id: number | null; qty: number; unit_price: number; confidence: number }[];
}

export function InvoiceForm({ po, open, onClose, endpoint }: { po: PODetail; open: boolean; onClose: () => void; endpoint?: string }) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const [no, setNo] = useState('');
  const [date, setDate] = useState(isoDate());
  const [rows, setRows] = useState<Record<number, { qty: string; price: string }>>({});
  const [conf, setConf] = useState<Record<number, number>>({});
  const [ocrMsg, setOcrMsg] = useState<string | null>(null);
  const scan = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('po_id', String(po.id));
      return api.upload<OcrResult>('/ocr/invoice', fd);
    },
    onSuccess: (r) => {
      if (r.invoice_no) setNo(r.invoice_no);
      if (r.invoice_date) setDate(r.invoice_date);
      const next = { ...rows };
      const c: Record<number, number> = {};
      r.lines.forEach((l) => {
        if (l.po_line_id && next[l.po_line_id]) {
          next[l.po_line_id] = { qty: String(l.qty), price: String(l.unit_price) };
          c[l.po_line_id] = l.confidence;
        }
      });
      setRows(next);
      setConf(c);
      const unmatched = r.lines.filter((l) => !l.po_line_id).length;
      setOcrMsg(t('ocr.result', { n: Object.keys(c).length, total: r.lines.length, conf: r.overall_confidence, unmatched }));
    },
    onError: (e) => toast.error(e),
  });
  useEffect(() => {
    if (open) setRows(Object.fromEntries(po.lines.map((l) => [l.id, { qty: String(l.received_qty || l.qty), price: String(l.unit_price) }])));
  }, [open, po.lines]);
  const save = useMutation({
    mutationFn: () => {
      const lines = Object.entries(rows).map(([id, r]) => ({ po_line_id: Number(id), qty: Number(r.qty), unit_price: Number(r.price) }));
      if (endpoint) {
        const fd = new FormData();
        fd.append('invoice_no', no);
        fd.append('invoice_date', date);
        fd.append('lines', JSON.stringify(lines));
        return api.upload<{ status: string }>(endpoint, fd);
      }
      return api.post<{ status: string }>(`/purchase-orders/${po.id}/invoices`, { invoice_no: no, invoice_date: date, lines });
    },
    onSuccess: (r) => {
      toast.success(t('orders.invoiceDone', { status: t(`status.${r.status}`, { defaultValue: r.status }) }));
      void qc.invalidateQueries();
      onClose();
    },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal open={open} onClose={onClose} wide title={`${t('orders.invoice')} — ${po.po_no}`}
      footer={<Button loading={save.isPending} disabled={!no.trim()} onClick={() => save.mutate()}>{t('common.save')}</Button>}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Input label={t('orders.invoiceNo')} value={no} onChange={(e) => setNo(e.target.value)} />
          <Input label={t('common.date')} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
        {po.lines.map((l) => rows[l.id] && (
          <div key={l.id} className="grid grid-cols-[1fr_6rem_7rem] items-end gap-2">
            <p className="truncate text-sm">{l.product}{conf[l.id] !== undefined && <Badge tone={conf[l.id] >= 85 ? 'green' : conf[l.id] >= 70 ? 'amber' : 'red'} className="ml-1">{t('ocr.confidence', { n: Math.round(conf[l.id]) })}</Badge>}</p>
            <Input label={t('common.qty')} type="number" value={rows[l.id].qty} onChange={(e) => setRows((r) => ({ ...r, [l.id]: { ...r[l.id], qty: e.target.value } }))} />
            <Input label={t('orders.rate')} type="number" step="0.01" value={rows[l.id].price} onChange={(e) => setRows((r) => ({ ...r, [l.id]: { ...r[l.id], price: e.target.value } }))} />
          </div>
        ))}
        <p className="text-xs text-slate-500">{t('orders.matchHint')}</p>
        {!endpoint && (
          <div className="rounded-lg border border-dashed border-slate-300 p-3 dark:border-slate-700">
            <label className="label" htmlFor="ocr-file">{t('ocr.scan')}</label>
            <input id="ocr-file" type="file" accept=".jpg,.jpeg,.png,.pdf" className="input" disabled={scan.isPending}
              onChange={(e) => e.target.files?.[0] && scan.mutate(e.target.files[0])} />
            {scan.isPending && <p className="mt-1 text-xs text-slate-500">{t('ocr.reading')}</p>}
            {ocrMsg && <p className="mt-1 text-xs text-violet-700 dark:text-violet-300">{ocrMsg}</p>}
          </div>
        )}
      </div>
    </Modal>
  );
}

function MatchCard({ po }: { po: PODetail }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [note, setNote] = useState('');
  const m = po.matches[0];
  const resolve = useMutation({
    mutationFn: () => api.post(`/matches/${m.id}/resolve`, { note }),
    onSuccess: () => { toast.success(t('orders.resolved')); void qc.invalidateQueries({ queryKey: ['po', String(po.id)] }); },
    onError: (e) => toast.error(e),
  });
  if (!m) return null;
  return (
    <Card title={t('orders.match')} actions={<StatusBadge status={m.status} />}>
      <p className="mb-2 text-xs text-slate-500">{t('orders.tolerance', { qty: m.details.tolerance.qty_pct, price: m.details.tolerance.price_pct })}</p>
      <div className="-mx-4 overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead><tr><th className="th">{t('nav.products')}</th><th className="th text-right">PO</th><th className="th text-right">GRN</th><th className="th text-right">{t('orders.invoice')}</th><th className="th text-right">{t('orders.poPrice')}</th><th className="th text-right">{t('orders.invPrice')}</th><th className="th text-right">Δ%</th><th className="th"></th></tr></thead>
          <tbody>
            {m.details.lines.map((l, i) => (
              <tr key={i} className={l.status === 'mismatch' ? 'bg-rose-50 dark:bg-rose-900/20' : ''}>
                <td className="td whitespace-normal">{l.product}{l.note ? ` — ${l.note}` : ''}</td>
                <td className="td text-right">{formatNum(l.po_qty)}</td><td className="td text-right">{formatNum(l.grn_qty)}</td><td className="td text-right">{formatNum(l.invoice_qty)}</td>
                <td className="td text-right">{formatINR(l.po_price)}</td><td className="td text-right">{formatINR(l.invoice_price)}</td>
                <td className="td text-right">{l.price_diff_pct === null ? '—' : `${l.price_diff_pct > 0 ? '+' : ''}${l.price_diff_pct}`}</td>
                <td className="td"><StatusBadge status={l.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {m.status === 'mismatch' && can('match.resolve') && (
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end">
          <Textarea className="flex-1" label={t('orders.resolution')} value={note} onChange={(e) => setNote(e.target.value)} />
          <Button loading={resolve.isPending} disabled={note.trim().length < 3} onClick={() => resolve.mutate()}>{t('orders.resolve')}</Button>
        </div>
      )}
      {m.resolution_note && <p className="mt-2 text-sm text-slate-600">{t('orders.resolution')}: {m.resolution_note}</p>}
    </Card>
  );
}

export default function OrderDetail() {
  const { id } = useParams();
  const { t } = useTranslation();
  const { can } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [grn, setGrn] = useState(false);
  const [inv, setInv] = useState(false);
  const [cancel, setCancel] = useState(false);
  const [reason, setReason] = useState('');
  const q = useQuery({ queryKey: ['po', id], queryFn: () => api.get<PODetail>(`/purchase-orders/${id}`) });
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => api.post<PODetail>(`/purchase-orders/${id}/${path}`, body),
    onSuccess: (d) => { qc.setQueryData(['po', id], d); toast.success(t('common.saved')); setCancel(false); },
    onError: (e) => toast.error(e),
  });
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <SkeletonRows rows={8} />;
  const po = q.data;
  const receivable = ['SENT', 'CONFIRMED', 'DISPATCHED', 'PARTIALLY_RECEIVED'].includes(po.status);
  const invoiceable = ['SENT', 'CONFIRMED', 'DISPATCHED', 'PARTIALLY_RECEIVED', 'RECEIVED'].includes(po.status) && po.invoices.length === 0;
  return (
    <div className="space-y-4">
      <Link to="/orders" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700"><ArrowLeft className="h-4 w-4" />{t('nav.orders')}</Link>
      <PageHeader title={po.po_no} subtitle={`${po.supplier} · ${po.location}`}
        actions={<>
          <StatusBadge status={po.status} />
          {po.late && <Badge tone="red">{t('orders.late')}</Badge>}
          <Button variant="secondary" icon={<FileDown className="h-4 w-4" />} onClick={() => api.open(`/purchase-orders/${po.id}/pdf`).catch(toast.error)}>PDF</Button>
          {can('po.write') && ['CREATED', 'SENT', 'CONFIRMED'].includes(po.status) && (
            <Button variant="secondary" icon={<Mail className="h-4 w-4" />} loading={act.isPending} onClick={() => act.mutate({ path: 'send' })}>{t('orders.resend')}</Button>
          )}
          {can('grn.write') && receivable && <Button icon={<PackageCheck className="h-4 w-4" />} onClick={() => setGrn(true)}>{t('orders.receive')}</Button>}
          {can('invoice.write') && invoiceable && <Button variant="secondary" icon={<Receipt className="h-4 w-4" />} onClick={() => setInv(true)}>{t('orders.addInvoice')}</Button>}
          {can('po.write') && ['CREATED', 'SENT', 'CONFIRMED', 'REJECTED_BY_SUPPLIER'].includes(po.status) && (
            <Button variant="danger" icon={<XCircle className="h-4 w-4" />} onClick={() => setCancel(true)}>{t('common.cancel')}</Button>
          )}
        </>} />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={t('orders.lines')} className="lg:col-span-2"><LinesTable po={po} /></Card>
        <Card title={t('orders.tracking')}>
          <KeyValue items={[
            [t('common.date'), formatDate(po.order_date)],
            [t('orders.expected'), formatDate(po.expected_date)],
            [t('orders.predicted'), formatDate(po.predicted_date)],
            [t('orders.eta'), formatDate(po.supplier_eta)],
            [t('orders.courier'), po.courier_name ? `${po.courier_name}${po.tracking_ref ? ` · ${po.tracking_ref}` : ''}` : '—'],
            [t('orders.courierStatus'), po.courier_status ?? '—'],
            ['GSTIN', po.supplier_detail.gstin ?? '—'],
          ]} />
          {po.rejection_reason && <p className="mt-2 text-sm text-rose-600">{po.rejection_reason}</p>}
          <div className="mt-4"><Timeline items={po.timeline} /></div>
        </Card>
        {po.grns.length > 0 && (
          <Card title={t('orders.grns')} className="lg:col-span-2">
            <ul className="space-y-3">
              {po.grns.map((g) => (
                <li key={g.id} className="text-sm">
                  <div className="flex items-center justify-between"><p className="font-medium">{g.grn_no} · {formatDateTime(g.received_at)}</p>
                    <Button size="sm" variant="ghost" icon={<FileDown className="h-3.5 w-3.5" />} onClick={() => api.open(`/goods-receipts/${g.id}/pdf`).catch(toast.error)}>PDF</Button></div>
                  <ul className="ml-3 text-xs text-slate-600 dark:text-slate-400">
                    {g.lines.map((l, i) => <li key={i}>{l.product}: {formatNum(l.received_qty)}{l.damaged_qty ? ` (+${formatNum(l.damaged_qty)} ${t('orders.damaged').toLowerCase()})` : ''} · {l.batch_no} · {formatDate(l.expiry_date)}</li>)}
                  </ul>
                </li>
              ))}
            </ul>
          </Card>
        )}
        {po.invoices.length > 0 && (
          <Card title={t('orders.invoices')}>
            <ul className="space-y-1 text-sm">{po.invoices.map((i) => <li key={i.id} className="flex justify-between"><span>{i.invoice_no} · {formatDate(i.invoice_date)}</span><span>{formatINR(i.total)} <StatusBadge status={i.status} /></span></li>)}</ul>
            {po.returns.map((r) => <p key={r.id} className="mt-2 text-xs"><Link className="text-brand-700 hover:underline dark:text-brand-400" to="/returns">{r.return_no}</Link> · {r.status}</p>)}
          </Card>
        )}
        <div className="lg:col-span-3"><MatchCard po={po} /></div>
      </div>
      <GrnForm po={po} open={grn} onClose={() => setGrn(false)} />
      <InvoiceForm po={po} open={inv} onClose={() => setInv(false)} />
      <Modal open={cancel} onClose={() => setCancel(false)} title={t('orders.cancelPo')}
        footer={<Button variant="danger" disabled={reason.trim().length < 3} loading={act.isPending} onClick={() => act.mutate({ path: 'cancel', body: { reason } })}>{t('common.confirm')}</Button>}>
        <Textarea label={t('common.reason')} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Modal>
    </div>
  );
}
