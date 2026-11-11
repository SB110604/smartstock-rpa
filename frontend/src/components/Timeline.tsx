import { useTranslation } from 'react-i18next';
import { formatDateTime } from '@/lib/format';
import { StatusBadge } from './ui';

export interface TimelineItem {
  from?: string | null;
  to: string;
  note?: string | null;
  actor_type?: string;
  at: string;
}

export function Timeline({ items }: { items: TimelineItem[] }) {
  const { t } = useTranslation();
  return (
    <ol className="relative space-y-3 border-l-2 border-brand-200 pl-4 dark:border-brand-900">
      {items.map((h, i) => (
        <li key={i} className="relative">
          <span className="absolute -left-[1.4rem] top-1 h-3 w-3 rounded-full border-2 border-white bg-brand-500 dark:border-slate-900" />
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <StatusBadge status={h.to} />
            <span className="text-xs text-slate-500">{formatDateTime(h.at)}</span>
            {h.actor_type && <span className="text-xs text-slate-400">· {t(`actor.${h.actor_type}`, { defaultValue: h.actor_type })}</span>}
          </div>
          {h.note && <p className="mt-0.5 text-xs text-slate-600 dark:text-slate-400">{h.note}</p>}
        </li>
      ))}
    </ol>
  );
}
