import {
  Activity,
  BarChart3,
  BellRing,
  LayoutDashboard,
  FileQuestion,
  FlaskConical,
  BrainCircuit,
  CalendarClock,
  ClipboardCheck,
  FileText,
  PackageOpen,
  Store,
  Undo2,
  Barcode,
  FileSpreadsheet,
  History,
  Package,
  Settings,
  ShoppingCart,
  Truck,
  Warehouse,
  type LucideIcon,
} from 'lucide-react';
import type { Role } from '@/lib/auth';

export interface NavItem {
  to: string;
  key: string;
  icon: LucideIcon;
  perm: string;
  group: 'operations' | 'purchasing' | 'ai' | 'admin' | 'supplier';
}

export const NAV: NavItem[] = [
  { to: '/', key: 'dashboard', icon: LayoutDashboard, perm: 'stock.read', group: 'operations' },
  { to: '/products', key: 'products', icon: Package, perm: 'products.read', group: 'operations' },
  { to: '/stock', key: 'stock', icon: Warehouse, perm: 'stock.read', group: 'operations' },
  { to: '/sales', key: 'sales', icon: ShoppingCart, perm: 'sales.write', group: 'operations' },
  { to: '/labels', key: 'labels', icon: Barcode, perm: 'labels.print', group: 'operations' },
  { to: '/expiry', key: 'expiry', icon: CalendarClock, perm: 'stock.read', group: 'operations' },
  { to: '/insights', key: 'insights', icon: BrainCircuit, perm: 'insights.read', group: 'ai' },
  { to: '/simulator', key: 'simulator', icon: FlaskConical, perm: 'simulator.use', group: 'ai' },
  { to: '/alerts', key: 'alerts', icon: BellRing, perm: 'alerts.read', group: 'operations' },
  { to: '/approvals', key: 'approvals', icon: ClipboardCheck, perm: 'purchasing.read', group: 'purchasing' },
  { to: '/orders', key: 'orders', icon: PackageOpen, perm: 'po.read', group: 'purchasing' },
  { to: '/rfqs', key: 'rfqs', icon: FileQuestion, perm: 'rfq.manage', group: 'purchasing' },
  { to: '/returns', key: 'returns', icon: Undo2, perm: 'returns.manage', group: 'purchasing' },
  { to: '/suppliers', key: 'suppliers', icon: Truck, perm: 'suppliers.read', group: 'purchasing' },
  { to: '/portal', key: 'portal', icon: Store, perm: 'portal.use', group: 'supplier' },
  { to: '/portal/rfqs', key: 'quotes', icon: FileQuestion, perm: 'portal.use', group: 'supplier' },
  { to: '/portal/invoices', key: 'invoices', icon: FileText, perm: 'portal.use', group: 'supplier' },
  { to: '/reports', key: 'reports', icon: BarChart3, perm: 'reports.read', group: 'ai' },
  { to: '/imports', key: 'imports', icon: FileSpreadsheet, perm: 'imports.run', group: 'admin' },
  { to: '/settings', key: 'settings', icon: Settings, perm: 'settings.read', group: 'admin' },
  { to: '/audit', key: 'audit', icon: History, perm: 'audit.read', group: 'admin' },
  { to: '/status', key: 'status', icon: Activity, perm: 'settings.read', group: 'admin' },
];

export const GROUPS: { id: NavItem['group']; key: string }[] = [
  { id: 'operations', key: 'groupOperations' },
  { id: 'purchasing', key: 'groupPurchasing' },
  { id: 'ai', key: 'groupAI' },
  { id: 'supplier', key: 'groupSupplier' },
  { id: 'admin', key: 'groupAdmin' },
];

export function homeFor(role: Role): string {
  return role === 'supplier' ? '/portal' : '/';
}
