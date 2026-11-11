import { describe, expect, it } from 'vitest';
import { formatDate, formatDateTime, formatINR, isoDate, titleCase } from '@/lib/format';

describe('format helpers', () => {
  it('formats dates as DD-MM-YYYY', () => {
    expect(formatDate('2026-03-05')).toBe('05-03-2026');
    expect(formatDate(null)).toBe('—');
    expect(formatDateTime(new Date(2026, 0, 2, 9, 7))).toBe('02-01-2026 09:07');
  });

  it('formats rupees with Indian grouping', () => {
    expect(formatINR(1234567.5)).toBe('₹12,34,567.50');
    expect(formatINR(500, false)).toBe('₹500');
    expect(formatINR(undefined)).toBe('—');
  });

  it('builds ISO dates and title case', () => {
    expect(isoDate(new Date(2026, 10, 2))).toBe('2026-11-02');
    expect(titleCase('pending_approval')).toBe('Pending Approval');
  });
});
