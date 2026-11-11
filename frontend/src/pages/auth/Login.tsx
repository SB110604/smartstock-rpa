import { zodResolver } from '@hookform/resolvers/zod';
import { Boxes } from 'lucide-react';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { z } from 'zod';
import { Button, Input } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { homeFor } from '@/layouts/nav';

const schema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
  totp: z.string().optional(),
});
type Form = z.infer<typeof schema>;

export function AuthShell({ title, children }: { title: string; children: React.ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-50 to-slate-100 px-4 dark:from-slate-950 dark:to-slate-900">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <Boxes className="h-12 w-12 text-brand-600" />
          <h1 className="text-2xl font-bold">{t('app.name')}</h1>
          <p className="text-sm text-slate-500">{t('app.tagline')}</p>
        </div>
        <div className="card p-6">
          <h2 className="mb-4 text-lg font-semibold">{title}</h2>
          {children}
        </div>
      </div>
    </div>
  );
}

export default function Login() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [needsTotp, setNeedsTotp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema) });

  const onSubmit = async (v: Form) => {
    setError(null);
    try {
      const me = await login(v.email, v.password, v.totp);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== '/login' ? from : homeFor(me.role), { replace: true });
    } catch (e) {
      if (e instanceof ApiError && e.code === 'totp_required') {
        setNeedsTotp(true);
        return;
      }
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <AuthShell title={t('auth.signIn')}>
      <form className="space-y-3" onSubmit={handleSubmit(onSubmit)} noValidate>
        <Input
          label={t('auth.email')}
          type="email"
          autoComplete="username"
          {...register('email')}
          error={formState.errors.email && t('auth.invalidEmail')}
        />
        <Input
          label={t('auth.password')}
          type="password"
          autoComplete="current-password"
          {...register('password')}
          error={formState.errors.password && t('common.required')}
        />
        {needsTotp && (
          <Input
            label={t('auth.totp')}
            inputMode="numeric"
            autoComplete="one-time-code"
            autoFocus
            maxLength={8}
            hint={t('auth.totpHint')}
            {...register('totp')}
          />
        )}
        {error && (
          <p
            className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-900/30 dark:text-rose-300"
            role="alert"
          >
            {error}
          </p>
        )}
        <Button type="submit" className="w-full" loading={formState.isSubmitting}>
          {t('auth.signIn')}
        </Button>
        <div className="text-center">
          <Link to="/forgot-password" className="text-sm text-brand-700 hover:underline dark:text-brand-400">
            {t('auth.forgot')}
          </Link>
        </div>
      </form>
    </AuthShell>
  );
}
