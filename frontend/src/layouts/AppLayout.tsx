import clsx from 'clsx';
import { Boxes, ChevronDown, LogOut, Menu, Moon, Search, Sun, User as UserIcon, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { LANGUAGES, setLanguage } from '@/i18n';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useTheme } from '@/lib/theme';
import { ChatButton, ChatPanel } from '@/components/ChatPanel';
import { NotificationBell } from '@/components/NotificationBell';
import { GROUPS, NAV } from './nav';

/** Top-bar search: PO numbers open the order list filtered, anything else searches products (name/SKU/barcode). */
function GlobalSearch() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  if (!can('products.read')) return null;
  const go = (e: React.FormEvent) => {
    e.preventDefault();
    const v = q.trim();
    if (!v) return;
    navigate(/^PO-/i.test(v) && can('po.read') ? `/orders?q=${encodeURIComponent(v)}` : `/products?q=${encodeURIComponent(v)}`);
    setQ('');
  };
  return (
    <form onSubmit={go} className="relative hidden max-w-sm sm:block" role="search">
      <Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-slate-400" />
      <input className="input py-1.5 pl-8" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('common.globalSearch')}
        aria-label={t('common.globalSearch')} />
    </form>
  );
}

function UserMenu() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);
  if (!user) return null;
  return (
    <div className="relative" ref={ref}>
      <button
        className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-600 text-xs font-bold text-white">
          {user.name.slice(0, 1).toUpperCase()}
        </span>
        <span className="hidden text-left sm:block">
          <span className="block max-w-[10rem] truncate text-xs font-semibold">{user.name}</span>
          <span className="block text-[11px] capitalize text-slate-500">{t(`roles.${user.role}`)}</span>
        </span>
        <ChevronDown className="hidden h-4 w-4 text-slate-400 sm:block" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 mt-1 w-48 overflow-hidden rounded-lg border border-slate-200 bg-white py-1 shadow-lg dark:border-slate-700 dark:bg-slate-900"
        >
          <p className="truncate px-3 py-1.5 text-xs text-slate-500">{user.email}</p>
          <button
            role="menuitem"
            className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-slate-100 dark:hover:bg-slate-800"
            onClick={() => {
              setOpen(false);
              navigate('/profile');
            }}
          >
            <UserIcon className="h-4 w-4" /> {t('common.profile')}
          </button>
          <button
            role="menuitem"
            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-rose-600 hover:bg-slate-100 dark:hover:bg-slate-800"
            onClick={async () => {
              await logout();
              navigate('/login');
            }}
          >
            <LogOut className="h-4 w-4" /> {t('common.logout')}
          </button>
        </div>
      )}
    </div>
  );
}

export default function AppLayout() {
  const { t, i18n } = useTranslation();
  const { user, can } = useAuth();
  const [theme, toggleTheme] = useTheme();
  const [open, setOpen] = useState(false);
  const [chat, setChat] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);

  const changeLang = (code: string) => {
    setLanguage(code);
    if (user) void api.patch('/auth/me', { language: code }).catch(() => undefined);
  };

  const items = NAV.filter((n) => can(n.perm));
  const sidebar = (
    <nav className="flex h-full flex-col overflow-y-auto p-3" aria-label="main">
      <Link to="/" className="mb-4 flex items-center gap-2 px-2">
        <Boxes className="h-7 w-7 text-brand-600" />
        <div>
          <p className="text-sm font-bold leading-tight">{t('app.name')}</p>
          <p className="text-[11px] leading-tight text-slate-500">{t('app.tagline')}</p>
        </div>
      </Link>
      {GROUPS.map((g) => {
        const groupItems = items.filter((i) => i.group === g.id);
        if (!groupItems.length) return null;
        return (
          <div key={g.id} className="mb-3">
            <p className="mb-1 px-2.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              {t(`nav.${g.key}`)}
            </p>
            {groupItems.map(({ to, key, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium',
                    isActive
                      ? 'bg-brand-50 text-brand-700 dark:bg-brand-900/30 dark:text-brand-300'
                      : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800',
                  )
                }
              >
                <Icon className="h-4 w-4 shrink-0" />
                {t(`nav.${key}`)}
              </NavLink>
            ))}
          </div>
        );
      })}
    </nav>
  );

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 lg:block">
        {sidebar}
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 bg-slate-900/50 lg:hidden" onClick={() => setOpen(false)}>
          <aside
            className="relative h-full w-64 max-w-[85vw] bg-white dark:bg-slate-900"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="absolute right-2 top-3 rounded p-1 text-slate-500"
              onClick={() => setOpen(false)}
              aria-label="close menu"
            >
              <X className="h-5 w-5" />
            </button>
            {sidebar}
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-1.5 border-b border-slate-200 bg-white/90 px-2 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90 sm:gap-2 sm:px-4">
          <button
            className="rounded p-1.5 lg:hidden"
            onClick={() => setOpen(true)}
            aria-label={t('common.menu')}
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="min-w-0 flex-1"><GlobalSearch /></div>
          <select
            className="input w-auto px-2 py-1.5 text-xs"
            value={i18n.language}
            onChange={(e) => changeLang(e.target.value)}
            aria-label={t('common.language')}
          >
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </select>
          <button
            className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            onClick={toggleTheme}
            aria-label={theme === 'dark' ? t('common.lightMode') : t('common.darkMode')}
          >
            {theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </button>
          {can('chat.use') && <ChatButton onClick={() => setChat(true)} />}
          <NotificationBell />
          <UserMenu />
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 p-3 sm:p-6">
          <Outlet />
        </main>
      </div>
      <ChatPanel open={chat} onClose={() => setChat(false)} />
    </div>
  );
}
