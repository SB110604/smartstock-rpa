const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 });
const inr0 = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
const num = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 });

export const formatINR = (v: number | string | null | undefined, decimals = true): string =>
  v === null || v === undefined || v === '' ? '—' : (decimals ? inr : inr0).format(Number(v));

export const formatNum = (v: number | string | null | undefined): string =>
  v === null || v === undefined || v === '' ? '—' : num.format(Number(v));

export const formatPct = (v: number | null | undefined, digits = 1): string =>
  v === null || v === undefined ? '—' : `${Number(v).toFixed(digits)}%`;

const pad = (n: number) => String(n).padStart(2, '0');

function toDate(v: string | Date): Date {
  if (v instanceof Date) return v;
  // Plain dates (YYYY-MM-DD) are calendar dates, not instants: build them in local time.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(v);
}

/** DD-MM-YYYY (spec: UI date format). */
export function formatDate(v: string | Date | null | undefined): string {
  if (!v) return '—';
  const d = toDate(v);
  if (Number.isNaN(d.getTime())) return '—';
  return `${pad(d.getDate())}-${pad(d.getMonth() + 1)}-${d.getFullYear()}`;
}

export function formatDateTime(v: string | Date | null | undefined): string {
  if (!v) return '—';
  const d = toDate(v);
  if (Number.isNaN(d.getTime())) return '—';
  return `${formatDate(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** YYYY-MM-DD for <input type="date"> and API params. */
export function isoDate(d: Date = new Date()): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function daysFromNow(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return isoDate(d);
}

export const titleCase = (s: string): string => s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
