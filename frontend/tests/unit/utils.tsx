import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import { AuthProvider } from '@/lib/auth';
import { ToastProvider } from '@/lib/toast';

export function renderApp(ui: ReactElement, path = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <ToastProvider>
          <AuthProvider>{ui}</AuthProvider>
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Route-based fetch mock: handlers keyed by "METHOD /path" (path without /api/v1 and query). */
export function mockFetch(handlers: Record<string, (body: unknown) => { status?: number; json: unknown }>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    const key = `${init?.method ?? 'GET'} ${url.pathname.replace('/api/v1', '')}`;
    const h = handlers[key];
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    const res = h ? h(body) : { status: 404, json: { detail: `no mock for ${key}`, code: 'not_found' } };
    return new Response(JSON.stringify(res.json), { status: res.status ?? 200, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}
