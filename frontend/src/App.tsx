import { lazy, Suspense, type ReactNode } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { RequireAuth, RequirePerm } from '@/components/RequireAuth';
import { SkeletonRows } from '@/components/ui';
import AppLayout from '@/layouts/AppLayout';
import { homeFor } from '@/layouts/nav';
import { useAuth } from '@/lib/auth';
import Login from '@/pages/auth/Login';
import { ForgotPassword, ResetPassword } from '@/pages/auth/PasswordReset';

const Products = lazy(() => import('@/pages/products/Products'));
const ProductDetail = lazy(() => import('@/pages/products/ProductDetail'));
const Suppliers = lazy(() => import('@/pages/suppliers/Suppliers'));
const SupplierDetail = lazy(() => import('@/pages/suppliers/SupplierDetail'));
const Stock = lazy(() => import('@/pages/stock/Stock'));
const Sales = lazy(() => import('@/pages/sales/Sales'));
const Imports = lazy(() => import('@/pages/tools/Imports'));
const Labels = lazy(() => import('@/pages/tools/Labels'));
const Settings = lazy(() => import('@/pages/admin/Settings'));
const Audit = lazy(() => import('@/pages/admin/Audit'));
const SystemStatus = lazy(() => import('@/pages/SystemStatus'));
const Profile = lazy(() => import('@/pages/Profile'));
const Approvals = lazy(() => import('@/pages/purchasing/Approvals'));
const Orders = lazy(() => import('@/pages/purchasing/Orders'));
const OrderDetail = lazy(() => import('@/pages/purchasing/OrderDetail'));
const Returns = lazy(() => import('@/pages/purchasing/Returns'));
const Alerts = lazy(() => import('@/pages/Alerts'));
const PortalHome = lazy(() => import('@/pages/portal/Portal').then((m) => ({ default: m.PortalHome })));
const PortalOrder = lazy(() => import('@/pages/portal/Portal').then((m) => ({ default: m.PortalOrder })));
const PortalInvoices = lazy(() => import('@/pages/portal/Portal').then((m) => ({ default: m.PortalInvoices })));
const Expiry = lazy(() => import('@/pages/stock/Expiry'));
const Insights = lazy(() => import('@/pages/insights/Insights'));
const Simulator = lazy(() => import('@/pages/insights/Simulator'));
const RfqList = lazy(() => import('@/pages/purchasing/Rfqs').then((m) => ({ default: m.RfqList })));
const RfqDetailPage = lazy(() => import('@/pages/purchasing/Rfqs').then((m) => ({ default: m.RfqDetailPage })));
const PortalRfqs = lazy(() => import('@/pages/portal/Portal').then((m) => ({ default: m.PortalRfqs })));
const PortalRfqDetail = lazy(() => import('@/pages/portal/Portal').then((m) => ({ default: m.PortalRfqDetail })));
const Dashboard = lazy(() => import('@/pages/Dashboard'));
const Reports = lazy(() => import('@/pages/Reports'));
const OneClickApproval = lazy(() => import('@/pages/auth/OneClickApproval'));

function Home() {
  const { user } = useAuth();
  return <Navigate to={user ? homeFor(user.role) : '/login'} replace />;
}

const page = (perm: string | null, el: ReactNode) =>
  perm ? <RequirePerm perm={perm}>{el}</RequirePerm> : el;

export default function App() {
  return (
    <Suspense
      fallback={
        <div className="p-6">
          <SkeletonRows rows={6} />
        </div>
      }
    >
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/approval" element={<OneClickApproval />} />
        <Route
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="products" element={page('products.read', <Products />)} />
          <Route path="products/:id" element={page('products.read', <ProductDetail />)} />
          <Route path="suppliers" element={page('suppliers.read', <Suppliers />)} />
          <Route path="suppliers/:id" element={page('suppliers.read', <SupplierDetail />)} />
          <Route path="stock" element={page('stock.read', <Stock />)} />
          <Route path="sales" element={page('sales.write', <Sales />)} />
          <Route path="imports" element={page('imports.run', <Imports />)} />
          <Route path="labels" element={page('labels.print', <Labels />)} />
          <Route path="settings" element={page('settings.read', <Settings />)} />
          <Route path="audit" element={page('audit.read', <Audit />)} />
          <Route path="status" element={page('settings.read', <SystemStatus />)} />
          <Route path="approvals" element={page('purchasing.read', <Approvals />)} />
          <Route path="orders" element={page('po.read', <Orders />)} />
          <Route path="orders/:id" element={page('po.read', <OrderDetail />)} />
          <Route path="returns" element={page('returns.manage', <Returns />)} />
          <Route path="expiry" element={page('stock.read', <Expiry />)} />
          <Route path="insights" element={page('insights.read', <Insights />)} />
          <Route path="simulator" element={page('simulator.use', <Simulator />)} />
          <Route path="rfqs" element={page('rfq.manage', <RfqList />)} />
          <Route path="rfqs/:id" element={page('rfq.manage', <RfqDetailPage />)} />
          <Route path="portal/rfqs" element={page('portal.use', <PortalRfqs />)} />
          <Route path="portal/rfqs/:id" element={page('portal.use', <PortalRfqDetail />)} />
          <Route path="reports" element={page('reports.read', <Reports />)} />
          <Route path="alerts" element={page('alerts.read', <Alerts />)} />
          <Route path="portal" element={page('portal.use', <PortalHome />)} />
          <Route path="portal/orders/:id" element={page('portal.use', <PortalOrder />)} />
          <Route path="portal/invoices" element={page('portal.use', <PortalInvoices />)} />
          <Route path="profile" element={<Profile />} />
          <Route path="*" element={<Home />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
