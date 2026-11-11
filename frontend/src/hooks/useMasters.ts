import { useQuery } from '@tanstack/react-query';
import type { Category, Location, Product, ProductRow, Supplier, SupplierRow } from '@/api/types';
import { api, type Page } from '@/lib/api';

export function useLocations() {
  return useQuery({
    queryKey: ['locations'],
    queryFn: () => api.get<Location[]>('/locations'),
    staleTime: 300_000,
  });
}

export function useCategories() {
  return useQuery({
    queryKey: ['categories'],
    queryFn: () => api.get<Category[]>('/categories'),
    staleTime: 300_000,
  });
}

export function useSupplierOptions(enabled = true) {
  return useQuery({
    queryKey: ['suppliers', 'options'],
    queryFn: () => api.get<Page<SupplierRow>>('/suppliers', { page_size: 500, is_active: true }),
    select: (d) => d.items as Supplier[],
    staleTime: 300_000,
    enabled,
  });
}

export function useProductOptions() {
  return useQuery({
    queryKey: ['products', 'options'],
    queryFn: () => api.get<Page<ProductRow>>('/products', { page_size: 500 }),
    select: (d) => d.items as Product[],
    staleTime: 120_000,
  });
}

export interface PublicSettings {
  business: {
    name: string;
    address: string;
    city: string;
    state: string;
    gstin: string;
    phone: string;
    email: string;
  };
  features: { llm_provider: string; telegram: boolean; imap: boolean; courier_provider: string };
  expiry_thresholds: { critical: number; warning: number };
}

export function usePublicSettings(enabled = true) {
  return useQuery({
    queryKey: ['settings', 'public'],
    queryFn: () => api.get<PublicSettings>('/settings/public'),
    staleTime: 300_000,
    enabled,
  });
}
