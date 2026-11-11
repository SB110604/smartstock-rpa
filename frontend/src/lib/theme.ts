import { useCallback, useEffect, useState } from 'react';

export type Theme = 'light' | 'dark';

function current(): Theme {
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light';
}

export function applyTheme(t: Theme): void {
  document.documentElement.classList.toggle('dark', t === 'dark');
  try {
    localStorage.setItem('ss.theme', t);
  } catch {
    /* preference not persisted */
  }
  window.dispatchEvent(new Event('ss:theme'));
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(current);
  useEffect(() => {
    const on = () => setTheme(current());
    window.addEventListener('ss:theme', on);
    return () => window.removeEventListener('ss:theme', on);
  }, []);
  const toggle = useCallback(() => applyTheme(current() === 'dark' ? 'light' : 'dark'), []);
  return [theme, toggle];
}
