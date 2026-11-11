import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Plus } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import type { Category, Location, SupplierRow, UserRow } from '@/api/types';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  DataTable,
  Input,
  Modal,
  PageHeader,
  Select,
  Tabs,
  Textarea,
} from '@/components/ui';
import { useCategories, useLocations, useSupplierOptions } from '@/hooks/useMasters';
import { api, type Page } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { formatDateTime } from '@/lib/format';
import { useToast } from '@/lib/toast';
import ApprovalRules from './ApprovalRules';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Values = Record<string, any>;
interface SettingsRes {
  values: Values;
  features: {
    llm_provider: string;
    telegram: boolean;
    imap: boolean;
    courier_provider: string;
    llm: { provider: string; configured: boolean; model: string | null; fallback: string };
    ocr: boolean;
  };
}

function useSettings() {
  return useQuery({ queryKey: ['settings', 'all'], queryFn: () => api.get<SettingsRes>('/settings') });
}

function useSaveSettings() {
  const qc = useQueryClient();
  const toast = useToast();
  const { t } = useTranslation();
  return useMutation({
    mutationFn: (v: Values) => api.put<SettingsRes>('/settings', v),
    onSuccess: (d) => {
      qc.setQueryData(['settings', 'all'], d);
      void qc.invalidateQueries({ queryKey: ['settings', 'public'] });
      toast.success(t('common.saved'));
    },
    onError: (e) => toast.error(e),
  });
}

function Business({ editable }: { editable: boolean }) {
  const { t } = useTranslation();
  const s = useSettings();
  const save = useSaveSettings();
  const [b, setB] = useState<Values>({});
  useEffect(() => {
    if (s.data) setB(s.data.values.business);
  }, [s.data]);
  const field = (k: string, label: string) => (
    <Input
      label={label}
      value={b[k] ?? ''}
      disabled={!editable}
      onChange={(e) => setB({ ...b, [k]: e.target.value })}
    />
  );
  return (
    <Card
      title={t('settings.business')}
      actions={
        editable && (
          <Button loading={save.isPending} onClick={() => save.mutate({ business: b })}>
            {t('common.save')}
          </Button>
        )
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {field('name', t('common.name'))}
        {field('gstin', 'GSTIN')}
        {field('address', t('suppliers.address'))}
        {field('city', t('settings.city'))}
        {field('state', t('suppliers.state'))}
        {field('phone', t('suppliers.phone'))}
        {field('email', t('auth.email'))}
      </div>
    </Card>
  );
}

function Integrations() {
  const { t } = useTranslation();
  const s = useSettings();
  const f = s.data?.features;
  if (!f) return null;
  const row = (label: string, ok: boolean, detail: string) => (
    <li className="flex items-center justify-between gap-2 py-2 text-sm">
      <span>{label}</span>
      <span className="flex items-center gap-2 text-xs text-slate-500">{detail}<Badge tone={ok ? 'green' : 'gray'}>{ok ? t('settings.on') : t('settings.off')}</Badge></span>
    </li>
  );
  return (
    <Card title={t('settings.integrations')} className="mt-4">
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {row(t('settings.llm'), f.llm.configured, f.llm.configured ? `${f.llm.provider} · ${f.llm.model}` : t('settings.llmFallback'))}
        {row('OCR (Tesseract)', f.ocr, f.ocr ? '' : t('settings.ocrMissing'))}
        {row('Telegram', f.telegram, f.telegram ? '' : 'TELEGRAM_BOT_TOKEN')}
        {row(t('settings.imap'), f.imap, f.imap ? '' : 'IMAP_HOST / IMAP_USER')}
        {row(t('settings.courier'), true, f.courier_provider)}
      </ul>
      <p className="mt-2 text-xs text-slate-500">{t('settings.integrationsHint')}</p>
    </Card>
  );
}

interface BackupFile {
  name: string;
  size: number;
  created_at: string;
}

function Backups() {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const [restoring, setRestoring] = useState<string | null>(null);
  const [confirm, setConfirm] = useState('');
  const q = useQuery({ queryKey: ['backups'], queryFn: () => api.get<BackupFile[]>('/backups') });
  const create = useMutation({ mutationFn: () => api.post<BackupFile>('/backups'),
    onSuccess: (b) => { toast.success(t('backup.created', { name: b.name })); void qc.invalidateQueries({ queryKey: ['backups'] }); },
    onError: (e) => toast.error(e) });
  const restore = useMutation({ mutationFn: () => api.post(`/backups/${restoring}/restore`, { confirm }),
    onSuccess: () => { toast.success(t('backup.restored')); setRestoring(null); setConfirm(''); qc.clear(); },
    onError: (e) => toast.error(e) });
  return (
    <Card title={t('backup.title')} actions={<Button loading={create.isPending} onClick={() => create.mutate()}>{t('backup.now')}</Button>}>
      <p className="mb-2 text-xs text-slate-500">{t('backup.hint')}</p>
      <DataTable<BackupFile> rows={q.data} loading={q.isLoading} error={q.error} rowKey={(b) => b.name} empty={t('backup.none')}
        columns={[
          { key: 'name', header: t('common.name'), className: 'font-mono text-xs' },
          { key: 'created_at', header: t('common.date'), render: (b) => formatDateTime(b.created_at) },
          { key: 'size', header: t('backup.size'), align: 'right', render: (b) => `${(b.size / 1024 / 1024).toFixed(1)} MB` },
          { key: 'a', header: '', render: (b) => <div className="flex justify-end gap-1">
            <Button size="sm" variant="secondary" onClick={() => api.download(`/backups/${b.name}`, b.name).catch(toast.error)}>{t('common.download')}</Button>
            <Button size="sm" variant="danger" onClick={() => setRestoring(b.name)}>{t('backup.restore')}</Button></div> },
        ]} />
      <Modal open={!!restoring} onClose={() => setRestoring(null)} title={t('backup.restoreTitle')}
        footer={<Button variant="danger" disabled={confirm !== 'RESTORE'} loading={restore.isPending} onClick={() => restore.mutate()}>{t('backup.restore')}</Button>}>
        <p className="mb-3 text-sm text-rose-700 dark:text-rose-300">{t('backup.warning', { name: restoring ?? '' })}</p>
        <Input label={t('backup.typeRestore')} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </Modal>
    </Card>
  );
}

function Parameters({ editable }: { editable: boolean }) {
  const { t } = useTranslation();
  const s = useSettings();
  const save = useSaveSettings();
  const [v, setV] = useState<Values | null>(null);
  useEffect(() => {
    if (s.data) setV(structuredClone(s.data.values));
  }, [s.data]);
  if (!v) return null;
  const num = (path: string[], label: string, step = '1', hint?: string) => {
    const val = path.reduce((o, k) => o?.[k], v as Values) as unknown as number | string | undefined;
    return (
      <Input
        label={label}
        type="number"
        step={step}
        value={val ?? ''}
        disabled={!editable}
        hint={hint}
        onChange={(e) => {
          const next = structuredClone(v);
          let o = next;
          path.slice(0, -1).forEach((k) => (o = o[k]));
          o[path[path.length - 1]] = e.target.value === '' ? '' : Number(e.target.value);
          setV(next);
        }}
      />
    );
  };
  const weights = v.supplier_weights;
  const wsum = ['price', 'ontime', 'lead', 'quality'].reduce((a, k) => a + Number(weights[k] || 0), 0);
  const keys = [
    'ordering_cost_S',
    'holding_cost_pct',
    'service_level',
    'review_period_days',
    'dead_stock_days',
    'approval_sla_hours',
    'supplier_weights',
    'expiry_thresholds',
    'match_tolerance',
    'markdown',
    'notification_channels',
    'po_terms',
  ];
  return (
    <div className="space-y-4">
      <Card title={t('settings.inventory')}>
        <div className="grid gap-3 sm:grid-cols-3">
          {num(['ordering_cost_S'], t('settings.orderingCost'), '1', '₹ per order (S)')}
          {num(['holding_cost_pct'], t('settings.holdingCost'), '0.1', '% of unit cost per year (H)')}
          {num(['service_level'], t('settings.serviceLevel'), '0.01', '0.50 – 0.999')}
          {num(['review_period_days'], t('settings.reviewPeriod'))}
          {num(['dead_stock_days'], t('settings.deadStockDays'))}
          {num(['approval_sla_hours'], t('settings.slaHours'))}
        </div>
      </Card>
      <Card title={t('settings.expiry')}>
        <div className="grid gap-3 sm:grid-cols-4">
          {num(['expiry_thresholds', 'critical'], t('settings.criticalDays'))}
          {num(['expiry_thresholds', 'warning'], t('settings.warningDays'))}
          {num(['markdown', 'critical_pct'], t('settings.criticalMarkdown'))}
          {num(['markdown', 'warning_pct'], t('settings.warningMarkdown'))}
        </div>
      </Card>
      <Card
        title={t('settings.weights')}
        actions={<Badge tone={Math.abs(wsum - 1) < 0.01 ? 'green' : 'red'}>Σ = {wsum.toFixed(2)}</Badge>}
      >
        <div className="grid gap-3 sm:grid-cols-4">
          {num(['supplier_weights', 'price'], t('suppliers.price'), '0.01')}
          {num(['supplier_weights', 'ontime'], t('suppliers.onTime'), '0.01')}
          {num(['supplier_weights', 'lead'], t('suppliers.lead'), '0.01')}
          {num(['supplier_weights', 'quality'], t('suppliers.quality'), '0.01')}
        </div>
      </Card>
      <Card title={t('settings.matching')}>
        <div className="grid gap-3 sm:grid-cols-2">
          {num(['match_tolerance', 'qty_pct'], t('settings.qtyTolerance'), '0.1')}
          {num(['match_tolerance', 'price_pct'], t('settings.priceTolerance'), '0.1')}
        </div>
      </Card>
      <Card title={t('settings.channels')}>
        <div className="flex flex-wrap gap-6">
          {(['in_app', 'email', 'telegram'] as const).map((c) => (
            <Checkbox
              key={c}
              label={t(`settings.channel_${c}`)}
              checked={!!v.notification_channels[c]}
              disabled={!editable || (c === 'telegram' && !s.data?.features.telegram)}
              onChange={(x) => setV({ ...v, notification_channels: { ...v.notification_channels, [c]: x } })}
            />
          ))}
        </div>
        {!s.data?.features.telegram && (
          <p className="mt-2 text-xs text-slate-500">{t('settings.telegramOff')}</p>
        )}
      </Card>
      <Card title={t('settings.poTerms')}>
        <Textarea
          rows={5}
          value={v.po_terms}
          disabled={!editable}
          onChange={(e) => setV({ ...v, po_terms: e.target.value })}
        />
      </Card>
      {editable && (
        <div className="flex justify-end">
          <Button
            loading={save.isPending}
            onClick={() => save.mutate(Object.fromEntries(keys.map((k) => [k, v[k]])))}
          >
            {t('common.save')}
          </Button>
        </div>
      )}
    </div>
  );
}

function Users() {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const suppliers = useSupplierOptions();
  const [edit, setEdit] = useState<(Partial<UserRow> & { password?: string }) | null>(null);
  const q = useQuery({
    queryKey: ['users'],
    queryFn: () => api.get<Page<UserRow>>('/users', { page_size: 200 }),
  });
  const save = useMutation({
    mutationFn: (u: Partial<UserRow> & { password?: string }) => {
      const body = {
        name: u.name,
        email: u.email,
        phone: u.phone || null,
        role: u.role,
        language: u.language ?? 'en',
        supplier_id: u.role === 'supplier' ? Number(u.supplier_id) || null : null,
        password: u.password || undefined,
        is_active: u.is_active,
        telegram_chat_id: u.telegram_chat_id || null,
      };
      return u.id ? api.patch(`/users/${u.id}`, { ...body, email: undefined }) : api.post('/users', body);
    },
    onSuccess: () => {
      toast.success(t('common.saved'));
      setEdit(null);
      void qc.invalidateQueries({ queryKey: ['users'] });
    },
    onError: (e) => toast.error(e),
  });
  return (
    <Card
      title={t('settings.users')}
      actions={
        <Button
          size="sm"
          icon={<Plus className="h-4 w-4" />}
          onClick={() => setEdit({ role: 'staff', language: 'en', is_active: true })}
        >
          {t('settings.newUser')}
        </Button>
      }
    >
      <DataTable<UserRow>
        rows={q.data?.items}
        loading={q.isLoading}
        error={q.error}
        rowKey={(u) => u.id}
        onRowClick={(u) => setEdit({ ...u })}
        columns={[
          {
            key: 'name',
            header: t('common.name'),
            render: (u) => (
              <div>
                <p className="font-medium">{u.name}</p>
                <p className="text-xs text-slate-500">{u.email}</p>
              </div>
            ),
          },
          {
            key: 'role',
            header: t('settings.role'),
            render: (u) => <Badge tone="blue">{t(`roles.${u.role}`)}</Badge>,
          },
          {
            key: 'totp_enabled',
            header: '2FA',
            render: (u) => (u.totp_enabled ? <Badge tone="green">On</Badge> : '—'),
          },
          {
            key: 'last_login_at',
            header: t('settings.lastLogin'),
            render: (u) => formatDateTime(u.last_login_at),
          },
          {
            key: 'is_active',
            header: t('common.status'),
            render: (u) =>
              u.is_active ? (
                <Badge tone="green">{t('products.active')}</Badge>
              ) : (
                <Badge>{t('products.inactive')}</Badge>
              ),
          },
        ]}
      />
      <Modal
        open={!!edit}
        onClose={() => setEdit(null)}
        title={edit?.id ? t('settings.editUser') : t('settings.newUser')}
        footer={
          <>
            <Button variant="secondary" onClick={() => setEdit(null)}>
              {t('common.cancel')}
            </Button>
            <Button loading={save.isPending} onClick={() => edit && save.mutate(edit)}>
              {t('common.save')}
            </Button>
          </>
        }
      >
        {edit && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              label={t('common.name')}
              value={edit.name ?? ''}
              onChange={(e) => setEdit({ ...edit, name: e.target.value })}
            />
            <Input
              label={t('auth.email')}
              type="email"
              value={edit.email ?? ''}
              disabled={!!edit.id}
              onChange={(e) => setEdit({ ...edit, email: e.target.value })}
            />
            <Input
              label={t('suppliers.phone')}
              value={edit.phone ?? ''}
              onChange={(e) => setEdit({ ...edit, phone: e.target.value })}
            />
            <Select
              label={t('settings.role')}
              value={edit.role}
              onChange={(e) => setEdit({ ...edit, role: e.target.value })}
              options={['admin', 'manager', 'staff', 'supplier'].map((r) => ({
                value: r,
                label: t(`roles.${r}`),
              }))}
            />
            {edit.role === 'supplier' && (
              <Select
                className="sm:col-span-2"
                label={t('nav.suppliers')}
                value={edit.supplier_id ?? ''}
                placeholder="—"
                onChange={(e) => setEdit({ ...edit, supplier_id: Number(e.target.value) })}
                options={(suppliers.data ?? []).map((s: SupplierRow | { id: number; name: string }) => ({
                  value: s.id,
                  label: s.name,
                }))}
              />
            )}
            <Select
              label={t('common.language')}
              value={edit.language}
              onChange={(e) => setEdit({ ...edit, language: e.target.value })}
              options={[
                { value: 'en', label: 'English' },
                { value: 'hi', label: 'हिन्दी' },
                { value: 'mr', label: 'मराठी' },
              ]}
            />
            <Input
              label={edit.id ? t('settings.newPassword') : t('auth.password')}
              type="password"
              value={edit.password ?? ''}
              hint={t('auth.passwordRule')}
              onChange={(e) => setEdit({ ...edit, password: e.target.value })}
            />
            <Input
              label={t('profile.telegram')}
              value={edit.telegram_chat_id ?? ''}
              onChange={(e) => setEdit({ ...edit, telegram_chat_id: e.target.value })}
            />
            {edit.id && (
              <Checkbox
                label={t('products.active')}
                checked={!!edit.is_active}
                onChange={(v) => setEdit({ ...edit, is_active: v })}
              />
            )}
          </div>
        )}
      </Modal>
    </Card>
  );
}

function Masters() {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const locs = useLocations();
  const cats = useCategories();
  const [cat, setCat] = useState<Partial<Category> | null>(null);
  const [loc, setLoc] = useState<Partial<Location> | null>(null);
  const saveCat = useMutation({
    mutationFn: (c: Partial<Category>) =>
      c.id ? api.put(`/categories/${c.id}`, { name: c.name }) : api.post('/categories', { name: c.name }),
    onSuccess: () => {
      setCat(null);
      void qc.invalidateQueries({ queryKey: ['categories'] });
      toast.success(t('common.saved'));
    },
    onError: (e) => toast.error(e),
  });
  const saveLoc = useMutation({
    mutationFn: (l: Partial<Location>) => {
      const body = {
        name: l.name,
        type: l.type ?? 'store',
        address: l.address || null,
        is_active: l.is_active ?? true,
      };
      return l.id ? api.put(`/locations/${l.id}`, body) : api.post('/locations', body);
    },
    onSuccess: () => {
      setLoc(null);
      void qc.invalidateQueries({ queryKey: ['locations'] });
      toast.success(t('common.saved'));
    },
    onError: (e) => toast.error(e),
  });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card
        title={t('settings.locations')}
        actions={
          <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setLoc({ type: 'store' })}>
            {t('common.add')}
          </Button>
        }
      >
        <DataTable<Location>
          rows={locs.data}
          loading={locs.isLoading}
          rowKey={(l) => l.id}
          onRowClick={(l) => setLoc({ ...l })}
          columns={[
            { key: 'name', header: t('common.name') },
            { key: 'type', header: t('stock.type'), render: (l) => t(`settings.loc_${l.type}`) },
            { key: 'address', header: t('suppliers.address'), render: (l) => l.address ?? '—' },
          ]}
        />
      </Card>
      <Card
        title={t('settings.categories')}
        actions={
          <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setCat({})}>
            {t('common.add')}
          </Button>
        }
      >
        <DataTable<Category>
          rows={cats.data}
          loading={cats.isLoading}
          rowKey={(c) => c.id}
          onRowClick={(c) => setCat({ ...c })}
          columns={[{ key: 'name', header: t('common.name') }]}
        />
      </Card>
      <Modal
        open={!!cat}
        onClose={() => setCat(null)}
        title={t('settings.categories')}
        footer={
          <Button loading={saveCat.isPending} onClick={() => cat && saveCat.mutate(cat)}>
            {t('common.save')}
          </Button>
        }
      >
        <Input
          label={t('common.name')}
          value={cat?.name ?? ''}
          onChange={(e) => setCat({ ...cat, name: e.target.value })}
          autoFocus
        />
      </Modal>
      <Modal
        open={!!loc}
        onClose={() => setLoc(null)}
        title={t('settings.locations')}
        footer={
          <Button loading={saveLoc.isPending} onClick={() => loc && saveLoc.mutate(loc)}>
            {t('common.save')}
          </Button>
        }
      >
        <div className="space-y-3">
          <Input
            label={t('common.name')}
            value={loc?.name ?? ''}
            onChange={(e) => setLoc({ ...loc, name: e.target.value })}
          />
          <Select
            label={t('stock.type')}
            value={loc?.type ?? 'store'}
            onChange={(e) => setLoc({ ...loc, type: e.target.value as Location['type'] })}
            options={[
              { value: 'store', label: t('settings.loc_store') },
              { value: 'warehouse', label: t('settings.loc_warehouse') },
            ]}
          />
          <Input
            label={t('suppliers.address')}
            value={loc?.address ?? ''}
            onChange={(e) => setLoc({ ...loc, address: e.target.value })}
          />
        </div>
      </Modal>
    </div>
  );
}

interface Key {
  id: number;
  name: string;
  prefix: string;
  location_id: number | null;
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
}

function ApiKeys() {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const locs = useLocations();
  const [name, setName] = useState('');
  const [loc, setLoc] = useState('');
  const [created, setCreated] = useState<string | null>(null);
  const q = useQuery({ queryKey: ['api-keys'], queryFn: () => api.get<Key[]>('/settings/api-keys') });
  const create = useMutation({
    mutationFn: () =>
      api.post<{ key: string }>('/settings/api-keys', { name, location_id: loc ? Number(loc) : null }),
    onSuccess: (r) => {
      setCreated(r.key);
      setName('');
      void qc.invalidateQueries({ queryKey: ['api-keys'] });
    },
    onError: (e) => toast.error(e),
  });
  const revoke = useMutation({
    mutationFn: (id: number) => api.del(`/settings/api-keys/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['api-keys'] }),
    onError: (e) => toast.error(e),
  });
  return (
    <Card title={t('settings.apiKeys')}>
      <p className="mb-3 text-xs text-slate-500">
        {t('settings.apiKeysHint')} <code>POST /api/v1/integrations/pos/sales</code> · <code>X-API-Key</code>
      </p>
      <div className="mb-3 grid gap-2 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <Input label={t('common.name')} value={name} onChange={(e) => setName(e.target.value)} />
        <Select
          label={t('stock.location')}
          value={loc}
          onChange={(e) => setLoc(e.target.value)}
          placeholder="—"
          options={(locs.data ?? []).map((l) => ({ value: l.id, label: l.name }))}
        />
        <Button disabled={name.trim().length < 2} loading={create.isPending} onClick={() => create.mutate()}>
          {t('common.create')}
        </Button>
      </div>
      {created && (
        <div className="mb-3 flex items-center gap-2 rounded-lg bg-amber-50 p-3 text-xs dark:bg-amber-900/30">
          <code className="flex-1 break-all">{created}</code>
          <Button
            size="sm"
            variant="secondary"
            icon={<Copy className="h-3.5 w-3.5" />}
            onClick={() =>
              void navigator.clipboard?.writeText(created).then(() => toast.success(t('settings.copied')))
            }
          >
            {t('settings.copy')}
          </Button>
        </div>
      )}
      <DataTable<Key>
        rows={q.data}
        loading={q.isLoading}
        rowKey={(k) => k.id}
        columns={[
          { key: 'name', header: t('common.name') },
          { key: 'prefix', header: t('settings.prefix'), render: (k) => <code>{k.prefix}…</code> },
          {
            key: 'last_used_at',
            header: t('settings.lastUsed'),
            render: (k) => formatDateTime(k.last_used_at),
          },
          {
            key: 'is_active',
            header: t('common.status'),
            render: (k) =>
              k.is_active ? (
                <Badge tone="green">{t('products.active')}</Badge>
              ) : (
                <Badge>{t('settings.revoked')}</Badge>
              ),
          },
          {
            key: 'a',
            header: '',
            render: (k) =>
              k.is_active && (
                <Button size="sm" variant="danger" onClick={() => revoke.mutate(k.id)}>
                  {t('settings.revoke')}
                </Button>
              ),
          },
        ]}
      />
    </Card>
  );
}

export default function Settings() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const admin = can('settings.manage');
  const [sp, setSp] = useSearchParams();
  const tabs = [
    { value: 'business', label: t('settings.business') },
    { value: 'parameters', label: t('settings.parameters') },
    ...(can('users.manage') ? [{ value: 'users', label: t('settings.users') }] : []),
    ...(can('masters.write') ? [{ value: 'masters', label: t('settings.masterData') }] : []),
    { value: 'rules', label: t('rules.title') },
    ...(admin ? [{ value: 'keys', label: t('settings.apiKeys') }, { value: 'backups', label: t('backup.title') }] : []),
  ];
  const tab = sp.get('tab') ?? 'business';
  return (
    <div>
      <PageHeader
        title={t('nav.settings')}
        subtitle={admin ? t('settings.subtitle') : t('settings.readOnly')}
      />
      <Tabs tabs={tabs} value={tab} onChange={(v) => setSp({ tab: v }, { replace: true })} />
      {tab === 'business' && (
        <>
          <Business editable={admin} />
          <Integrations />
        </>
      )}
      {tab === 'parameters' && <Parameters editable={admin} />}
      {tab === 'users' && <Users />}
      {tab === 'masters' && <Masters />}
      {tab === 'rules' && <ApprovalRules editable={admin} />}
      {tab === 'keys' && <ApiKeys />}
      {tab === 'backups' && <Backups />}
    </div>
  );
}
