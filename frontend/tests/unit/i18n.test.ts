import { describe, expect, it } from 'vitest';
import en from '@/i18n/locales/en.json';
import hi from '@/i18n/locales/hi.json';
import mr from '@/i18n/locales/mr.json';

type Tree = Record<string, Record<string, string>>;
const flat = (t: Tree) => Object.entries(t).flatMap(([s, v]) => Object.entries(v).map(([k, x]) => [`${s}.${k}`, x] as const));
const placeholders = (s: string) => (s.match(/{{\w+}}/g) ?? []).sort().join(',');

describe('translations', () => {
  const base = new Map(flat(en as Tree));
  it.each([['hi', hi], ['mr', mr]])('%s has every English key with the same placeholders', (_, tree) => {
    const other = new Map(flat(tree as Tree));
    expect([...base.keys()].filter((k) => !other.has(k))).toEqual([]);
    expect([...other.keys()].filter((k) => !base.has(k))).toEqual([]);
    for (const [k, v] of base) expect(placeholders(other.get(k)!), k).toBe(placeholders(v));
  });
  it('actually translates (not just copies English)', () => {
    expect((hi as Tree).nav.dashboard).toBe('डैशबोर्ड');
    expect((mr as Tree).nav.products).toBe('उत्पादने');
  });
});
