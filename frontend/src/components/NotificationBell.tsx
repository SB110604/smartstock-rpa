import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { Bell } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { api, type Page } from '@/lib/api';
import { formatDateTime } from '@/lib/format';

interface Item {
  id: number;
  title: string;
  body: string | null;
  link: string | null;
  created_at: string;
  read_at: string | null;
}

export function NotificationBell() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const count = useQuery({
    queryKey: ['notifications', 'count'],
    queryFn: () => api.get<{ unread: number }>('/notifications/unread-count'),
    refetchInterval: 30_000,
  });
  const list = useQuery({
    queryKey: ['notifications', 'list'],
    queryFn: () => api.get<Page<Item>>('/notifications', { page_size: 15 }),
    enabled: open,
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ['notifications'] });
  const read = useMutation({ mutationFn: (id: number) => api.post(`/notifications/${id}/read`), onSuccess: refresh });
  const readAll = useMutation({ mutationFn: () => api.post('/notifications/read-all'), onSuccess: refresh });
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);
  const unread = count.data?.unread ?? 0;
  return (
    <div className="relative" ref={ref}>
      <button
        className="relative rounded-lg p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
        onClick={() => setOpen((o) => !o)}
        aria-label={`${t('common.notifications')} (${unread})`}
      >
        <Bell className="h-5 w-5" />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-600 px-1 text-[10px] font-bold text-white">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="fixed inset-x-2 top-14 z-50 rounded-xl border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-900 sm:absolute sm:inset-x-auto sm:right-0 sm:top-auto sm:mt-1 sm:w-96">
          <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2 dark:border-slate-800">
            <p className="text-sm font-semibold">{t('common.notifications')}</p>
            <button className="text-xs text-brand-700 hover:underline dark:text-brand-400" onClick={() => readAll.mutate()}>
              {t('common.markAllRead')}
            </button>
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {(list.data?.items ?? []).map((n) => (
              <li key={n.id}>
                <button
                  className={clsx('w-full px-3 py-2 text-left hover:bg-slate-50 dark:hover:bg-slate-800', !n.read_at && 'bg-brand-50/60 dark:bg-brand-900/20')}
                  onClick={() => {
                    if (!n.read_at) read.mutate(n.id);
                    setOpen(false);
                    if (n.link) navigate(n.link);
                  }}
                >
                  <p className="text-sm font-medium">{n.title}</p>
                  {n.body && <p className="line-clamp-2 text-xs text-slate-600 dark:text-slate-400">{n.body}</p>}
                  <p className="mt-0.5 text-[11px] text-slate-400">{formatDateTime(n.created_at)}</p>
                </button>
              </li>
            ))}
            {list.data?.items.length === 0 && <li className="px-3 py-6 text-center text-sm text-slate-500">{t('common.noNotifications')}</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
