import { useMutation, useQuery } from '@tanstack/react-query';
import { CheckCircle2, XCircle } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { Button, KeyValue, SkeletonRows, Textarea } from '@/components/ui';
import { api } from '@/lib/api';
import { formatDateTime, formatINR, formatNum } from '@/lib/format';
import { errorMessage } from '@/lib/toast';
import { AuthShell } from './Login';

interface Info {
  action: 'approve' | 'reject';
  level: number;
  approver: string | null;
  expires_at: string;
  request: { id: number; product: string; qty: number; unit: string; supplier: string | null; est_total: number; reason_text: string | null };
}

/** Public page behind the email/Telegram links. A confirm click is required so link scanners can't approve. */
export default function OneClickApproval() {
  const { t } = useTranslation();
  const [sp] = useSearchParams();
  const token = sp.get('token') ?? '';
  const [reason, setReason] = useState('');
  const info = useQuery({ queryKey: ['token', token], queryFn: () => api.get<Info>(`/approvals/token/${token}`), retry: false });
  const go = useMutation({ mutationFn: () => api.post<{ detail: string }>(`/approvals/token/${token}`, { reason: reason || null }) });
  const d = info.data;
  return (
    <AuthShell title={d ? t(d.action === 'approve' ? 'oneclick.approveTitle' : 'oneclick.rejectTitle', { id: d.request.id }) : t('oneclick.title')}>
      {info.isLoading && <SkeletonRows rows={4} cols={2} />}
      {info.error && <p className="text-sm text-rose-600" role="alert">{errorMessage(info.error)}</p>}
      {go.isSuccess ? (
        <p className="flex items-center gap-2 text-sm text-emerald-700"><CheckCircle2 className="h-5 w-5" />{go.data.detail}</p>
      ) : d && (
        <div className="space-y-3">
          <KeyValue items={[
            [t('common.product'), d.request.product],
            [t('common.qty'), `${formatNum(d.request.qty)} ${d.request.unit}`],
            [t('common.supplier'), d.request.supplier ?? '—'],
            [t('approvals.estTotal'), formatINR(d.request.est_total)],
          ]} />
          {d.request.reason_text && <p className="rounded bg-slate-50 p-2 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">{d.request.reason_text}</p>}
          {d.action === 'reject' && <Textarea label={t('oneclick.reason')} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />}
          {go.error && <p className="text-sm text-rose-600" role="alert">{errorMessage(go.error)}</p>}
          <Button className="w-full" variant={d.action === 'approve' ? 'success' : 'danger'} loading={go.isPending}
            disabled={d.action === 'reject' && reason.trim().length < 3}
            icon={d.action === 'approve' ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />} onClick={() => go.mutate()}>
            {d.action === 'approve' ? t('approvals.approve') : t('approvals.reject')}
          </Button>
          <p className="text-center text-xs text-slate-500">{t('oneclick.expires', { at: formatDateTime(d.expires_at), who: d.approver ?? '' })}</p>
        </div>
      )}
    </AuthShell>
  );
}
