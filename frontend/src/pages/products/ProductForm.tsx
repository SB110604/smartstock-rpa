import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';
import type { Product } from '@/api/types';
import { Button, Checkbox, Input, Modal, Select } from '@/components/ui';
import { useCategories } from '@/hooks/useMasters';
import { api } from '@/lib/api';
import { useToast } from '@/lib/toast';

const num = (min = 0) => z.coerce.number({ invalid_type_error: 'Enter a number' }).min(min);

const schema = z
  .object({
    sku: z.string().trim().min(2).max(40),
    barcode: z.string().trim().max(64).optional().or(z.literal('')),
    name: z.string().trim().min(2).max(200),
    category_id: z.coerce.number().optional().or(z.literal('')),
    unit: z.string().trim().min(1).max(12),
    hsn_code: z.string().trim().max(12).optional().or(z.literal('')),
    gst_rate: z.coerce
      .number()
      .refine((v) => [0, 5, 12, 18, 28].includes(v), 'GST must be 0, 5, 12, 18 or 28'),
    cost_price: num(),
    selling_price: num(),
    is_perishable: z.boolean(),
    shelf_life_days: z.coerce.number().int().min(1).optional().or(z.literal('')),
    min_order_qty: num(0.001),
    pack_size: num(0.001),
    is_active: z.boolean(),
  })
  .refine((v) => !v.is_perishable || !!v.shelf_life_days, {
    path: ['shelf_life_days'],
    message: 'Required for perishables',
  })
  .refine((v) => v.selling_price >= v.cost_price, {
    path: ['selling_price'],
    message: 'Selling price is below cost',
  });

type FormValues = z.infer<typeof schema>;

export default function ProductForm({
  product,
  open,
  onClose,
}: {
  product?: Product | null;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const cats = useCategories();
  const { register, handleSubmit, watch, setValue, formState } = useForm<FormValues>({
    resolver: zodResolver(schema),
    values: {
      sku: product?.sku ?? '',
      barcode: product?.barcode ?? '',
      name: product?.name ?? '',
      category_id: product?.category_id ?? '',
      unit: product?.unit ?? 'pcs',
      hsn_code: product?.hsn_code ?? '',
      gst_rate: product?.gst_rate ?? 5,
      cost_price: product?.cost_price ?? 0,
      selling_price: product?.selling_price ?? 0,
      is_perishable: product?.is_perishable ?? false,
      shelf_life_days: product?.shelf_life_days ?? '',
      min_order_qty: product?.min_order_qty ?? 1,
      pack_size: product?.pack_size ?? 1,
      is_active: product?.is_active ?? true,
    },
  });
  const save = useMutation({
    mutationFn: (v: FormValues) => {
      const body = {
        ...v,
        barcode: v.barcode || null,
        hsn_code: v.hsn_code || null,
        category_id: v.category_id === '' ? null : v.category_id,
        shelf_life_days: v.shelf_life_days === '' ? null : v.shelf_life_days,
      };
      return product
        ? api.put<Product>(`/products/${product.id}`, body)
        : api.post<Product>('/products', body);
    },
    onSuccess: () => {
      toast.success(t('common.saved'));
      void qc.invalidateQueries({ queryKey: ['products'] });
      onClose();
    },
    onError: (e) => toast.error(e),
  });
  const e = formState.errors;
  const perishable = watch('is_perishable');
  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title={product ? t('products.edit') : t('products.new')}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleSubmit((v) => save.mutate(v))} loading={save.isPending}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <form className="grid grid-cols-1 gap-3 sm:grid-cols-3" onSubmit={handleSubmit((v) => save.mutate(v))}>
        <Input label={t('products.sku')} {...register('sku')} error={e.sku?.message} />
        <Input label={t('products.barcode')} {...register('barcode')} error={e.barcode?.message} />
        <Select
          label={t('products.category')}
          {...register('category_id')}
          placeholder="—"
          options={(cats.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
        />
        <Input
          className="sm:col-span-2"
          label={t('common.name')}
          {...register('name')}
          error={e.name?.message}
        />
        <Input
          label={t('products.unit')}
          {...register('unit')}
          error={e.unit?.message}
          hint="pcs, kg, ltr, pack"
        />
        <Input label={t('products.hsn')} {...register('hsn_code')} />
        <Select
          label={t('products.gst')}
          {...register('gst_rate')}
          error={e.gst_rate?.message}
          options={[0, 5, 12, 18, 28].map((r) => ({ value: r, label: `${r}%` }))}
        />
        <Input
          label={t('products.cost')}
          type="number"
          step="0.01"
          {...register('cost_price')}
          error={e.cost_price?.message}
        />
        <Input
          label={t('products.price')}
          type="number"
          step="0.01"
          {...register('selling_price')}
          error={e.selling_price?.message}
        />
        <Input
          label={t('products.moq')}
          type="number"
          step="0.001"
          {...register('min_order_qty')}
          error={e.min_order_qty?.message}
        />
        <Input
          label={t('products.pack')}
          type="number"
          step="0.001"
          {...register('pack_size')}
          error={e.pack_size?.message}
        />
        <div className="flex flex-col justify-end gap-2 sm:col-span-3 sm:flex-row sm:items-center sm:justify-start sm:gap-6">
          <Checkbox
            label={t('products.perishable')}
            checked={perishable}
            onChange={(v) => setValue('is_perishable', v)}
          />
          <Checkbox
            label={t('products.active')}
            checked={watch('is_active')}
            onChange={(v) => setValue('is_active', v)}
          />
        </div>
        {perishable && (
          <Input
            label={t('products.shelfLife')}
            type="number"
            {...register('shelf_life_days')}
            error={e.shelf_life_days?.message}
          />
        )}
      </form>
    </Modal>
  );
}
