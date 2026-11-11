import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { Lookup, ProductRow } from '@/api/types';
import { api, type Page } from '@/lib/api';
import { formatINR, formatNum } from '@/lib/format';
import { useToast } from '@/lib/toast';
import { ScanButton, ScannerModal } from './Scanner';

function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

/** Search by name/SKU/barcode or scan with the camera; resolves to a full stock lookup for the location. */
export function ProductPicker({
  onPick,
  locationId,
  placeholder,
  autoFocus,
}: {
  onPick: (l: Lookup) => void;
  locationId?: number;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [scan, setScan] = useState(false);
  const [active, setActive] = useState(0);
  const dq = useDebounced(q);
  const box = useRef<HTMLDivElement>(null);

  const results = useQuery({
    queryKey: ['products', 'search', dq],
    queryFn: () => api.get<Page<ProductRow>>('/products', { q: dq, page_size: 8 }),
    enabled: dq.trim().length >= 2,
  });

  useEffect(() => {
    const close = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  const resolve = useCallback(
    async (code: string) => {
      try {
        const l = await api.get<Lookup>('/stock/lookup', { code, location_id: locationId });
        onPick(l);
        setQ('');
        setOpen(false);
      } catch (e) {
        toast.error(e);
      }
    },
    [locationId, onPick, toast],
  );

  const onDetected = useCallback(
    (code: string) => {
      setScan(false);
      void resolve(code);
    },
    [resolve],
  );

  const items = results.data?.items ?? [];
  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') setActive((a) => Math.min(a + 1, items.length - 1));
    else if (e.key === 'ArrowUp') setActive((a) => Math.max(a - 1, 0));
    else if (e.key === 'Enter') {
      e.preventDefault();
      // USB barcode scanners "type" the code then press Enter: resolve it directly.
      if (items[active] && open) void resolve(items[active].sku);
      else if (q.trim()) void resolve(q.trim());
    } else if (e.key === 'Escape') setOpen(false);
  };

  return (
    <div className="flex gap-2" ref={box}>
      <div className="relative flex-1">
        <input
          className="input"
          value={q}
          autoFocus={autoFocus}
          placeholder={placeholder ?? t('scan.searchPlaceholder')}
          aria-label={placeholder ?? t('scan.searchPlaceholder')}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
            setActive(0);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKey}
          role="combobox"
          aria-expanded={open && items.length > 0}
        />
        {open && items.length > 0 && (
          <ul
            className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900"
            role="listbox"
          >
            {items.map((p, i) => (
              <li key={p.id} role="option" aria-selected={i === active}>
                <button
                  type="button"
                  className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm ${i === active ? 'bg-brand-50 dark:bg-brand-900/30' : ''}`}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => void resolve(p.sku)}
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{p.name}</span>
                    <span className="text-xs text-slate-500">{p.sku}</span>
                  </span>
                  <span className="shrink-0 text-right text-xs text-slate-500">
                    {formatINR(p.selling_price)}
                    <br />
                    {formatNum(p.on_hand)} {p.unit}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <ScanButton onClick={() => setScan(true)} />
      <ScannerModal open={scan} onClose={() => setScan(false)} onDetected={onDetected} />
    </div>
  );
}
