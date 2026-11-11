const BASE = import.meta.env.VITE_API_BASE ?? '/api/v1';
const TOKEN_KEY = 'ss.tokens';

export interface Tokens {
  access_token: string;
  refresh_token: string;
}

export class ApiError extends Error {
  status: number;
  code: string;
  errors?: { field: string; message: string }[];
  constructor(status: number, detail: string, code: string, errors?: { field: string; message: string }[]) {
    super(detail);
    this.status = status;
    this.code = code;
    this.errors = errors;
  }
}

export function getTokens(): Tokens | null {
  try {
    const raw = localStorage.getItem(TOKEN_KEY);
    return raw ? (JSON.parse(raw) as Tokens) : null;
  } catch {
    return null;
  }
}

export function setTokens(t: Tokens | null): void {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, JSON.stringify(t));
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: tokens live only for this page load */
  }
  window.dispatchEvent(new Event('ss:auth'));
}

type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

export function buildQuery(q?: Query): string {
  if (!q) return '';
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === null || v === '') continue;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)));
    else p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : '';
}

let refreshing: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  const t = getTokens();
  if (!t?.refresh_token) return false;
  refreshing ??= fetch(`${BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: t.refresh_token }),
  })
    .then(async (r) => {
      if (!r.ok) {
        setTokens(null);
        return false;
      }
      setTokens((await r.json()) as Tokens);
      return true;
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

interface Opts {
  query?: Query;
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
}

async function raw(method: string, path: string, opts: Opts = {}, retried = false): Promise<Response> {
  const headers: Record<string, string> = {};
  const t = getTokens();
  if (t?.access_token) headers.Authorization = `Bearer ${t.access_token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(`${BASE}${path}${buildQuery(opts.query)}`, {
    method,
    headers,
    body,
    signal: opts.signal,
  });
  if (res.status === 401 && !retried && !path.startsWith('/auth/login') && (await refreshTokens())) {
    return raw(method, path, opts, true);
  }
  if (!res.ok) {
    let detail = res.statusText || 'Request failed';
    let code = 'error';
    let errors;
    try {
      const j = await res.json();
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
      code = j.code ?? code;
      errors = j.errors;
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 401) setTokens(null);
    throw new ApiError(res.status, detail, code, errors);
  }
  return res;
}

async function json<T>(method: string, path: string, opts?: Opts): Promise<T> {
  const res = await raw(method, path, opts);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => json<T>('GET', path, { query, signal }),
  post: <T>(path: string, body?: unknown, query?: Query) => json<T>('POST', path, { body, query }),
  put: <T>(path: string, body?: unknown) => json<T>('PUT', path, { body }),
  patch: <T>(path: string, body?: unknown) => json<T>('PATCH', path, { body }),
  del: <T>(path: string) => json<T>('DELETE', path),
  upload: <T>(path: string, form: FormData, query?: Query) => json<T>('POST', path, { form, query }),
  /** Fetch a binary (PDF/Excel) with auth and trigger a browser download. */
  async download(path: string, filename: string, query?: Query): Promise<void> {
    const res = await raw('GET', path, { query });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  },
  /** Fetch a binary and open it in a new tab (PDF preview / print). */
  async open(path: string, query?: Query, body?: unknown): Promise<void> {
    const win = window.open('', '_blank');
    try {
      const res = await raw(body === undefined ? 'GET' : 'POST', path, { query, body });
      const url = URL.createObjectURL(await res.blob());
      if (win) win.location.href = url;
      else window.location.href = url;
    } catch (e) {
      win?.close();
      throw e;
    }
  },
};

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
