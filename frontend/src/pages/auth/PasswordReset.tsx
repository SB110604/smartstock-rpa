import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Button, Input } from '@/components/ui';
import { api } from '@/lib/api';
import { errorMessage, useToast } from '@/lib/toast';
import { AuthShell } from './Login';

export function ForgotPassword() {
  const { t } = useTranslation();
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.post<{ detail: string }>('/auth/forgot-password', { email });
      setSent(r.detail);
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthShell title={t('auth.forgotTitle')}>
      {sent ? (
        <p className="text-sm text-slate-600 dark:text-slate-300">{sent}</p>
      ) : (
        <form className="space-y-3" onSubmit={submit}>
          <p className="text-sm text-slate-500">{t('auth.forgotHint')}</p>
          <Input
            label={t('auth.email')}
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Button type="submit" className="w-full" loading={busy}>
            {t('auth.sendLink')}
          </Button>
        </form>
      )}
      <div className="mt-4 text-center">
        <Link to="/login" className="text-sm text-brand-700 hover:underline dark:text-brand-400">
          {t('auth.backToLogin')}
        </Link>
      </div>
    </AuthShell>
  );
}

export function ResetPassword() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pw !== pw2) {
      setError(t('auth.mismatch'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ detail: string }>('/auth/reset-password', {
        token: params.get('token') ?? '',
        password: pw,
      });
      toast.success(r.detail);
      navigate('/login');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthShell title={t('auth.resetTitle')}>
      <form className="space-y-3" onSubmit={submit}>
        <Input
          label={t('auth.newPassword')}
          type="password"
          autoComplete="new-password"
          required
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          hint={t('auth.passwordRule')}
        />
        <Input
          label={t('auth.confirmPassword')}
          type="password"
          autoComplete="new-password"
          required
          value={pw2}
          onChange={(e) => setPw2(e.target.value)}
        />
        {error && (
          <p className="text-sm text-rose-600" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" className="w-full" loading={busy}>
          {t('auth.resetTitle')}
        </Button>
      </form>
    </AuthShell>
  );
}
