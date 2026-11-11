import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Badge, Button, Card, ErrorState, PageHeader, SkeletonRows } from '@/components/ui';
import { api } from '@/lib/api';

interface Component {
  status: string;
  error?: string;
  workers?: string[];
  last_seconds_ago?: number;
}
type Health = { status: string } & Record<'db' | 'redis' | 'worker' | 'beat', Component>;

export default function SystemStatus() {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['health'],
    queryFn: () => api.get<Health>('/health'),
    refetchInterval: 15000,
  });
  const tone = (s: string) => (s === 'ok' ? 'green' : s === 'degraded' || s === 'stale' ? 'amber' : 'red');
  return (
    <div>
      <PageHeader
        title={t('system.title')}
        subtitle={t('system.subtitle')}
        actions={
          <Button variant="secondary" onClick={() => q.refetch()} loading={q.isFetching}>
            {t('common.refresh')}
          </Button>
        }
      />
      <Card>
        {q.error ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : !q.data ? (
          <SkeletonRows rows={5} cols={2} />
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            <li className="flex items-center justify-between py-2 text-sm font-semibold">
              {t('system.overall')} <Badge tone={tone(q.data.status)}>{q.data.status}</Badge>
            </li>
            {(['db', 'redis', 'worker', 'beat'] as const).map((k) => (
              <li key={k} className="flex items-center justify-between py-2 text-sm">
                <span>
                  {t(`system.${k}`)}
                  {q.data[k].workers && q.data[k].workers!.length > 0 && (
                    <span className="ml-2 text-xs text-slate-500">{q.data[k].workers!.join(', ')}</span>
                  )}
                  {q.data[k].last_seconds_ago !== undefined && (
                    <span className="ml-2 text-xs text-slate-500">{q.data[k].last_seconds_ago}s</span>
                  )}
                </span>
                <Badge tone={tone(q.data[k].status)}>{q.data[k].status}</Badge>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
