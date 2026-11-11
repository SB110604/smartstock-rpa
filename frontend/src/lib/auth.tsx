import { useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { setLanguage } from '@/i18n';
import { api, ApiError, getTokens, setTokens, type Tokens } from './api';

export type Role = 'admin' | 'manager' | 'staff' | 'supplier';

export interface Me {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  role: Role;
  supplier_id: number | null;
  supplier_name: string | null;
  language: string;
  totp_enabled: boolean;
  telegram_chat_id: string | null;
  permissions: string[];
}

interface AuthState {
  user: Me | null;
  loading: boolean;
  login: (email: string, password: string, totp?: string) => Promise<Me>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
  can: (permission: string) => boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState<boolean>(() => !!getTokens());
  const qc = useQueryClient();

  const refreshMe = useCallback(async () => {
    if (!getTokens()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api.get<Me>('/auth/me');
      setUser(me);
      if (me.language) setLanguage(me.language);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshMe();
    const onAuth = () => {
      if (!getTokens()) setUser(null);
    };
    window.addEventListener('ss:auth', onAuth);
    return () => window.removeEventListener('ss:auth', onAuth);
  }, [refreshMe]);

  const login = useCallback(async (email: string, password: string, totp?: string) => {
    const res = await api.post<Tokens & { user: Me }>('/auth/login', {
      email,
      password,
      totp_code: totp || undefined,
    });
    setTokens({ access_token: res.access_token, refresh_token: res.refresh_token });
    setUser(res.user);
    if (res.user.language) setLanguage(res.user.language);
    return res.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout');
    } catch {
      /* token may already be invalid */
    }
    setTokens(null);
    setUser(null);
    qc.clear();
  }, [qc]);

  const can = useCallback((p: string) => !!user?.permissions.includes(p), [user]);

  const value = useMemo(
    () => ({ user, loading, login, logout, refreshMe, can }),
    [user, loading, login, logout, refreshMe, can],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const c = useContext(Ctx);
  if (!c) throw new Error('useAuth outside AuthProvider');
  return c;
}
