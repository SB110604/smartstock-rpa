import { useEffect, useState } from 'react';
import { useLocations } from './useMasters';

const KEY = 'ss.location';

/** The location the user is working at, remembered per browser; defaults to the first store. */
export function useCurrentLocation(): [number | undefined, (id: number) => void] {
  const locs = useLocations();
  const [id, setId] = useState<number | undefined>(() => {
    try {
      const v = localStorage.getItem(KEY);
      return v ? Number(v) : undefined;
    } catch {
      return undefined;
    }
  });
  useEffect(() => {
    if (!locs.data?.length) return;
    if (!id || !locs.data.some((l) => l.id === id))
      setId((locs.data.find((l) => l.type === 'store') ?? locs.data[0]).id);
  }, [locs.data, id]);
  const set = (v: number) => {
    setId(v);
    try {
      localStorage.setItem(KEY, String(v));
    } catch {
      /* not persisted */
    }
  };
  return [id, set];
}
