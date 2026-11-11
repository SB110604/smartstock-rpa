import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { z } from 'zod';
import type { Supplier, SupplierRow } from '@/api/types';
import {
  Badge,
  Button,
  Card,
  DataTable,
  Input,
  Modal,
  PageHeader,
  Pagination,
  SearchBox,
  Textarea,
} from '@/components/ui';
import { api, type Page } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { formatPct } from '@/lib/format';
import { useToast } from '@/lib/toast';

const schema = z.object({
  name: z.string().trim().min(2).max(200),
  contact_name: z.string().trim().max(120).optional(),
  email: z.string().trim().email().optional().or(z.literal('')),
  phone: z.string().trim().max(20).optional(),
  gstin: z
    .string()
    .trim()
    .toUpperCase()
    .regex(/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/, 'Invalid GSTIN (e.g. 27ABCDE1234F1Z5)')
    .optional()
    .or(z.literal('')),
  state: z.string().trim().min(2).max(60),
  address: z.string().trim().optional(),
  payment_terms_days: z.coerce.number().int().min(0).max(365),
});
type FormValues = z.infer<typeof schema>;

export function SupplierForm({
  supplier,
  open,
  onClose,
}: {
  supplier?: Supplier | null;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const { register, handleSubmit, formState } = useForm<FormValues>({
    resolver: zodResolver(schema),
    values: {
      name: supplier?.name ?? '',
      contact_name: supplier?.contact_name ?? '',
      email: supplier?.email ?? '',
      phone: supplier?.phone ?? '',
      gstin: supplier?.gstin ?? '',
      state: supplier?.state ?? 'Maharashtra',
      address: supplier?.address ?? '',
      payment_terms_days: supplier?.payment_terms_days ?? 30,
    },
  });
  const save = useMutation({
    mutationFn: (v: FormValues) => {
      const body = {
        ...v,
        email: v.email || null,
        gstin: v.gstin || null,
        is_active: supplier?.is_active ?? true,
      };
      return supplier ? api.put(`/suppliers/${supplier.id}`, body) : api.post('/suppliers', body);
    },
    onSuccess: () => {
      toast.success(t('common.saved'));
      void qc.invalidateQueries({ queryKey: ['suppliers'] });
      onClose();
    },
    onError: (e) => toast.error(e),
  });
  const e = formState.errors;
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={supplier ? t('suppliers.edit') : t('suppliers.new')}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button loading={save.isPending} onClick={handleSubmit((v) => save.mutate(v))}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <form className="grid grid-cols-1 gap-3 sm:grid-cols-2" onSubmit={handleSubmit((v) => save.mutate(v))}>
        <Input
          className="sm:col-span-2"
          label={t('common.name')}
          {...register('name')}
          error={e.name?.message}
        />
        <Input label={t('suppliers.contact')} {...register('contact_name')} />
        <Input label={t('suppliers.phone')} {...register('phone')} />
        <Input label={t('auth.email')} type="email" {...register('email')} error={e.email?.message} />
        <Input label="GSTIN" {...register('gstin')} error={e.gstin?.message} />
        <Input label={t('suppliers.state')} {...register('state')} error={e.state?.message} />
        <Input
          label={t('suppliers.terms')}
          type="number"
          {...register('payment_terms_days')}
          error={e.payment_terms_days?.message}
        />
        <Textarea className="sm:col-span-2" label={t('suppliers.address')} {...register('address')} />
      </form>
    </Modal>
  );
}

export default function Suppliers() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [form, setForm] = useState(false);
  const data = useQuery({
    queryKey: ['suppliers', q, page],
    queryFn: () => api.get<Page<SupplierRow>>('/suppliers', { q, page, page_size: 25 }),
  });
  return (
    <div>
      <PageHeader
        title={t('nav.suppliers')}
        subtitle={t('suppliers.subtitle')}
        actions={
          can('suppliers.write') && (
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => setForm(true)}>
              {t('suppliers.new')}
            </Button>
          )
        }
      />
      <Card>
        <div className="mb-3">
          <SearchBox
            value={q}
            onChange={(v) => {
              setQ(v);
              setPage(1);
            }}
          />
        </div>
        <DataTable<SupplierRow>
          rows={data.data?.items}
          loading={data.isLoading}
          error={data.error}
          onRetry={() => data.refetch()}
          rowKey={(s) => s.id}
          onRowClick={(s) => navigate(`/suppliers/${s.id}`)}
          columns={[
            {
              key: 'name',
              header: t('common.name'),
              render: (s) => (
                <div>
                  <p className="font-medium">{s.name}</p>
                  <p className="text-xs text-slate-500">{s.contact_name ?? ''}</p>
                </div>
              ),
            },
            { key: 'state', header: t('suppliers.state') },
            { key: 'gstin', header: 'GSTIN', className: 'font-mono text-xs' },
            { key: 'products', header: t('nav.products'), align: 'right' },
            {
              key: 'on_time_pct',
              header: t('suppliers.onTime'),
              align: 'right',
              render: (s) => formatPct(s.on_time_pct),
            },
            {
              key: 'score',
              header: t('suppliers.score'),
              align: 'right',
              render: (s) =>
                s.score === null ? (
                  '—'
                ) : (
                  <Badge tone={s.score >= 75 ? 'green' : s.score >= 55 ? 'amber' : 'red'}>
                    {s.score.toFixed(1)}
                  </Badge>
                ),
            },
            {
              key: 'is_active',
              header: t('common.status'),
              render: (s) =>
                s.is_active ? (
                  <Badge tone="green">{t('products.active')}</Badge>
                ) : (
                  <Badge>{t('products.inactive')}</Badge>
                ),
            },
          ]}
        />
        {data.data && <Pagination page={page} pageSize={25} total={data.data.total} onPage={setPage} />}
      </Card>
      <SupplierForm open={form} onClose={() => setForm(false)} />
    </div>
  );
}
