import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Badge, Button, Card, Input, PageHeader, Select } from '@/components/ui';
import { setLanguage } from '@/i18n';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useToast } from '@/lib/toast';

function TwoFactor() {
  const { t } = useTranslation();
  const { user, refreshMe } = useAuth();
  const toast = useToast();
  const [setup, setSetup] = useState<{ secret: string; qr_png_base64: string } | null>(null);
  const [code, setCode] = useState('');
  const start = useMutation({
    mutationFn: () => api.post<{ secret: string; qr_png_base64: string }>('/auth/2fa/setup'),
    onSuccess: setSetup,
    onError: (e) => toast.error(e),
  });
  const enable = useMutation({
    mutationFn: () => api.post('/auth/2fa/enable', { code }),
    onSuccess: async () => {
      setSetup(null);
      setCode('');
      await refreshMe();
      toast.success(t('profile.twoFaOn'));
    },
    onError: (e) => toast.error(e),
  });
  const disable = useMutation({
    mutationFn: () => api.post('/auth/2fa/disable', { code }),
    onSuccess: async () => {
      setCode('');
      await refreshMe();
      toast.success(t('profile.twoFaOff'));
    },
    onError: (e) => toast.error(e),
  });
  if (user?.role !== 'admin') return null;
  return (
    <Card
      title={t('profile.twoFa')}
      actions={user.totp_enabled ? <Badge tone="green">On</Badge> : <Badge>Off</Badge>}
    >
      {user.totp_enabled ? (
        <div className="flex flex-wrap items-end gap-2">
          <Input
            label={t('auth.totp')}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            inputMode="numeric"
          />
          <Button
            variant="danger"
            loading={disable.isPending}
            disabled={code.length < 6}
            onClick={() => disable.mutate()}
          >
            {t('profile.disable2fa')}
          </Button>
        </div>
      ) : setup ? (
        <div className="space-y-3">
          <p className="text-sm">{t('profile.scanQr')}</p>
          <img
            src={`data:image/png;base64,${setup.qr_png_base64}`}
            alt="2FA QR"
            className="h-44 w-44 rounded bg-white p-2"
          />
          <p className="break-all text-xs text-slate-500">
            {t('profile.secret')}: <code>{setup.secret}</code>
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <Input
              label={t('auth.totp')}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              inputMode="numeric"
            />
            <Button loading={enable.isPending} disabled={code.length < 6} onClick={() => enable.mutate()}>
              {t('profile.enable2fa')}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-sm text-slate-500">{t('profile.twoFaHint')}</p>
          <Button loading={start.isPending} onClick={() => start.mutate()}>
            {t('profile.setup2fa')}
          </Button>
        </div>
      )}
    </Card>
  );
}

export default function Profile() {
  const { t } = useTranslation();
  const { user, refreshMe, logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [p, setP] = useState({
    name: user?.name ?? '',
    phone: user?.phone ?? '',
    language: user?.language ?? 'en',
    telegram_chat_id: user?.telegram_chat_id ?? '',
  });
  const [pw, setPw] = useState({ current_password: '', new_password: '' });
  const save = useMutation({
    mutationFn: () =>
      api.patch('/auth/me', { ...p, phone: p.phone || null, telegram_chat_id: p.telegram_chat_id || null }),
    onSuccess: async () => {
      setLanguage(p.language);
      await refreshMe();
      toast.success(t('common.saved'));
    },
    onError: (e) => toast.error(e),
  });
  const change = useMutation({
    mutationFn: () => api.post<{ detail: string }>('/auth/change-password', pw),
    onSuccess: async (r) => {
      toast.success(r.detail);
      await logout();
      navigate('/login');
    },
    onError: (e) => toast.error(e),
  });
  if (!user) return null;
  return (
    <div className="space-y-4">
      <PageHeader
        title={t('common.profile')}
        subtitle={`${user.email} · ${t(`roles.${user.role}`)}${user.supplier_name ? ` · ${user.supplier_name}` : ''}`}
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title={t('profile.details')}
          actions={
            <Button loading={save.isPending} onClick={() => save.mutate()}>
              {t('common.save')}
            </Button>
          }
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              label={t('common.name')}
              value={p.name}
              onChange={(e) => setP({ ...p, name: e.target.value })}
            />
            <Input
              label={t('suppliers.phone')}
              value={p.phone}
              onChange={(e) => setP({ ...p, phone: e.target.value })}
            />
            <Select
              label={t('common.language')}
              value={p.language}
              onChange={(e) => setP({ ...p, language: e.target.value })}
              options={[
                { value: 'en', label: 'English' },
                { value: 'hi', label: 'हिन्दी' },
                { value: 'mr', label: 'मराठी' },
              ]}
            />
            <Input
              label={t('profile.telegram')}
              value={p.telegram_chat_id}
              hint={t('profile.telegramHint')}
              onChange={(e) => setP({ ...p, telegram_chat_id: e.target.value })}
            />
          </div>
        </Card>
        <Card
          title={t('profile.changePassword')}
          actions={
            <Button
              loading={change.isPending}
              disabled={!pw.current_password || pw.new_password.length < 8}
              onClick={() => change.mutate()}
            >
              {t('common.save')}
            </Button>
          }
        >
          <div className="grid gap-3">
            <Input
              label={t('profile.currentPassword')}
              type="password"
              autoComplete="current-password"
              value={pw.current_password}
              onChange={(e) => setPw({ ...pw, current_password: e.target.value })}
            />
            <Input
              label={t('auth.newPassword')}
              type="password"
              autoComplete="new-password"
              value={pw.new_password}
              hint={t('auth.passwordRule')}
              onChange={(e) => setPw({ ...pw, new_password: e.target.value })}
            />
          </div>
        </Card>
        <TwoFactor />
      </div>
    </div>
  );
}
