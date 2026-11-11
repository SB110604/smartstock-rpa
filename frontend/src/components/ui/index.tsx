import clsx from 'clsx';
import { ChevronLeft, ChevronRight, Inbox, Loader2, Search, X } from 'lucide-react';
import {
  forwardRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
  useEffect,
  useId,
} from 'react';
import { useTranslation } from 'react-i18next';

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost' | 'success';

const variants: Record<Variant, string> = {
  primary: 'bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-600/50',
  secondary:
    'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800',
  danger: 'bg-rose-600 text-white hover:bg-rose-700 disabled:bg-rose-600/50',
  success: 'bg-emerald-600 text-white hover:bg-emerald-700',
  ghost: 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800',
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: 'sm' | 'md';
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'primary',
    size = 'md',
    loading,
    icon,
    className,
    children,
    disabled,
    type = 'button',
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:cursor-not-allowed',
        size === 'sm' ? 'px-2.5 py-1.5 text-xs' : 'px-3.5 py-2 text-sm',
        variants[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
});

interface FieldProps {
  label?: string;
  error?: string;
  hint?: string;
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & FieldProps>(
  function Input({ label, error, hint, className, id, ...rest }, ref) {
    const auto = useId();
    const fid = id ?? rest.name ?? auto;
    return (
      <div className={className}>
        {label && (
          <label htmlFor={fid} className="label">
            {label}
          </label>
        )}
        <input ref={ref} id={fid} className={clsx('input', error && 'border-rose-500')} {...rest} />
        {error ? (
          <p className="mt-1 text-xs text-rose-600">{error}</p>
        ) : (
          hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>
        )}
      </div>
    );
  },
);

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement> & FieldProps
>(function Textarea({ label, error, className, id, ...rest }, ref) {
  const auto = useId();
    const fid = id ?? rest.name ?? auto;
  return (
    <div className={className}>
      {label && (
        <label htmlFor={fid} className="label">
          {label}
        </label>
      )}
      <textarea ref={ref} id={fid} className={clsx('input', error && 'border-rose-500')} rows={3} {...rest} />
      {error && <p className="mt-1 text-xs text-rose-600">{error}</p>}
    </div>
  );
});

export interface Option {
  value: string | number;
  label: string;
}

export const Select = forwardRef<
  HTMLSelectElement,
  SelectHTMLAttributes<HTMLSelectElement> & FieldProps & { options: Option[]; placeholder?: string }
>(function Select({ label, error, options, placeholder, className, id, ...rest }, ref) {
  const auto = useId();
    const fid = id ?? rest.name ?? auto;
  return (
    <div className={className}>
      {label && (
        <label htmlFor={fid} className="label">
          {label}
        </label>
      )}
      <select ref={ref} id={fid} className={clsx('input', error && 'border-rose-500')} {...rest}>
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {error && <p className="mt-1 text-xs text-rose-600">{error}</p>}
    </div>
  );
});

export function Checkbox({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
      <input
        type="checkbox"
        className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  );
}

export function Card({
  title,
  actions,
  children,
  className,
  bodyClass,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClass?: string;
}) {
  return (
    <section className={clsx('card', className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          {typeof title === 'string' ? <h2 className="text-sm font-semibold">{title}</h2> : title}
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={clsx('p-4', bodyClass)}>{children}</div>
    </section>
  );
}

const tones = {
  gray: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  green: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
  red: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300',
  amber: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  blue: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300',
  purple: 'bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300',
};
export type Tone = keyof typeof tones;

export function Badge({
  tone = 'gray',
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

const statusTones: Record<string, Tone> = {
  draft: 'gray',
  pending_approval: 'amber',
  approved: 'green',
  rejected: 'red',
  ordered: 'blue',
  cancelled: 'gray',
  created: 'gray',
  sent: 'blue',
  confirmed: 'purple',
  dispatched: 'purple',
  partially_received: 'amber',
  received: 'green',
  invoiced: 'blue',
  closed: 'green',
  rejected_by_supplier: 'red',
  open: 'red',
  acknowledged: 'amber',
  resolved: 'green',
  matched: 'green',
  mismatch: 'red',
  requested: 'amber',
  in_transit: 'purple',
  credit_received: 'green',
  submitted: 'blue',
  awarded: 'green',
  success: 'green',
  failed: 'red',
  running: 'blue',
  partial: 'amber',
  pending: 'amber',
  accepted: 'green',
  critical: 'red',
  warning: 'amber',
  info: 'blue',
  expired: 'red',
  ok: 'green',
};

export function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  const key = status.toLowerCase();
  return (
    <Badge tone={statusTones[key] ?? 'gray'}>
      {t(`status.${key}`, { defaultValue: key.replace(/_/g, ' ') })}
    </Badge>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('animate-pulse rounded-md bg-slate-200 dark:bg-slate-800', className)} />;
}

export function SkeletonRows({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-3">
          {Array.from({ length: cols }).map((__, j) => (
            <Skeleton key={j} className="h-6 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <Inbox className="h-10 w-10 text-slate-300 dark:text-slate-600" />
      <p className="text-sm font-medium text-slate-600 dark:text-slate-300">{title}</p>
      {hint && <p className="max-w-sm text-xs text-slate-500">{hint}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation();
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex flex-col items-center gap-2 py-8 text-center" role="alert">
      <p className="text-sm font-medium text-rose-600">{t('common.loadFailed')}</p>
      <p className="text-xs text-slate-500">{msg}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          {t('common.retry')}
        </Button>
      )}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-0 sm:items-center sm:p-4"
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={clsx(
          'max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-white shadow-xl dark:bg-slate-900 sm:rounded-2xl',
          wide ? 'sm:max-w-4xl' : 'sm:max-w-lg',
        )}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
          <h3 className="text-base font-semibold">{title}</h3>
          <button
            className="rounded p-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
            onClick={onClose}
            aria-label="close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-4">{children}</div>
        {footer && (
          <div className="sticky bottom-0 flex justify-end gap-2 border-t border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

export function SearchBox({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="relative w-full sm:w-64">
      <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
      <input
        className="input pl-8"
        value={value}
        placeholder={placeholder ?? t('common.search')}
        onChange={(e) => onChange(e.target.value)}
        aria-label={placeholder ?? t('common.search')}
      />
    </div>
  );
}

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  sortable?: boolean;
  className?: string;
  align?: 'right' | 'left';
}

export function DataTable<T>({
  columns,
  rows,
  loading,
  error,
  onRetry,
  rowKey,
  empty,
  sort,
  onSort,
  onRowClick,
  selectable,
  selected,
  onSelect,
}: {
  columns: Column<T>[];
  rows: T[] | undefined;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  rowKey: (row: T) => string | number;
  empty?: string;
  sort?: string;
  onSort?: (s: string) => void;
  onRowClick?: (row: T) => void;
  selectable?: boolean;
  selected?: Set<string | number>;
  onSelect?: (s: Set<string | number>) => void;
}) {
  const { t } = useTranslation();
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (loading || !rows) return <SkeletonRows cols={Math.min(columns.length, 5)} />;
  if (rows.length === 0) return <EmptyState title={empty ?? t('common.noData')} />;
  const allKeys = rows.map(rowKey);
  const allSelected = selectable && selected && allKeys.every((k) => selected.has(k));
  const toggle = (k: string | number) => {
    if (!selected || !onSelect) return;
    const s = new Set(selected);
    if (s.has(k)) s.delete(k);
    else s.add(k);
    onSelect(s);
  };
  return (
    <div className="-mx-4 overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
        <thead>
          <tr>
            {selectable && (
              <th className="th w-8">
                <input
                  type="checkbox"
                  aria-label="select all"
                  checked={!!allSelected}
                  onChange={() => onSelect?.(allSelected ? new Set() : new Set(allKeys))}
                />
              </th>
            )}
            {columns.map((c) => {
              const active = sort?.replace('-', '') === c.key;
              return (
                <th key={c.key} className={clsx('th', c.align === 'right' && 'text-right', c.className)}>
                  {c.sortable && onSort ? (
                    <button
                      className="inline-flex items-center gap-1 uppercase hover:text-slate-800 dark:hover:text-slate-200"
                      onClick={() => onSort(active && !sort?.startsWith('-') ? `-${c.key}` : c.key)}
                    >
                      {c.header}
                      {active && <span>{sort?.startsWith('-') ? '↓' : '↑'}</span>}
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {rows.map((r) => {
            const k = rowKey(r);
            return (
              <tr
                key={k}
                className={clsx(
                  onRowClick && 'cursor-pointer',
                  'hover:bg-slate-50 dark:hover:bg-slate-800/50',
                )}
                onClick={onRowClick ? () => onRowClick(r) : undefined}
              >
                {selectable && (
                  <td className="td" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      aria-label="select row"
                      checked={selected?.has(k) ?? false}
                      onChange={() => toggle(k)}
                    />
                  </td>
                )}
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={clsx('td', c.align === 'right' && 'text-right tabular-nums', c.className)}
                  >
                    {c.render ? c.render(r) : String((r as Record<string, unknown>)[c.key] ?? '—')}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
}) {
  const { t } = useTranslation();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total === 0) return null;
  return (
    <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
      <span>
        {t('common.showing', {
          from: (page - 1) * pageSize + 1,
          to: Math.min(page * pageSize, total),
          total,
        })}
      </span>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
          aria-label="previous page"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span>
          {page} / {pages}
        </span>
        <Button
          variant="ghost"
          size="sm"
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
          aria-label="next page"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { value: T; label: string; count?: number }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div
      className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200 dark:border-slate-800"
      role="tablist"
    >
      {tabs.map((tb) => (
        <button
          key={tb.value}
          role="tab"
          aria-selected={value === tb.value}
          onClick={() => onChange(tb.value)}
          className={clsx(
            '-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium',
            value === tb.value
              ? 'border-brand-600 text-brand-700 dark:text-brand-400'
              : 'border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300',
          )}
        >
          {tb.label}
          {tb.count !== undefined && (
            <span className="ml-1.5 rounded-full bg-slate-100 px-1.5 text-xs dark:bg-slate-800">
              {tb.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: 'red' | 'amber' | 'green';
}) {
  return (
    <div className="card p-4">
      <p className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</p>
      <p
        className={clsx(
          'mt-1 text-2xl font-semibold tabular-nums',
          tone === 'red' && 'text-rose-600',
          tone === 'amber' && 'text-amber-600',
          tone === 'green' && 'text-emerald-600',
        )}
      >
        {value}
      </p>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
      {items.map(([k, v]) => (
        <div
          key={k}
          className="flex justify-between gap-3 border-b border-dashed border-slate-200 pb-1 text-sm dark:border-slate-800"
        >
          <dt className="text-slate-500">{k}</dt>
          <dd className="text-right font-medium">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
