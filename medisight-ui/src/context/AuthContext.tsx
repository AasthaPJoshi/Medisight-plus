/**
 * FILE: src/context/AuthContext.tsx
 * Global authentication state. Persists token + user to localStorage.
 * Wrap the entire app with <AuthProvider> so any component can call useAuth().
 */

import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import type { AuthUser, UserRole } from '../lib/types';

interface AuthState {
  user: AuthUser | null;
  token: string | null;
  role: UserRole | null;
  isAuthenticated: boolean;
}

interface AuthContextValue extends AuthState {
  login:  (user: AuthUser) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const STORAGE_KEY_TOKEN = 'ms_token';
const STORAGE_KEY_USER  = 'ms_user';

function loadFromStorage(): AuthState {
  try {
    const token = localStorage.getItem(STORAGE_KEY_TOKEN);
    const raw   = localStorage.getItem(STORAGE_KEY_USER);
    if (token && raw) {
      const user = JSON.parse(raw) as AuthUser;
      return { user, token, role: user.role as UserRole, isAuthenticated: true };
    }
  } catch { /* ignore */ }
  return { user: null, token: null, role: null, isAuthenticated: false };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState>(loadFromStorage);

  const login = useCallback((user: AuthUser) => {
    localStorage.setItem(STORAGE_KEY_TOKEN, user.access_token);
    localStorage.setItem(STORAGE_KEY_USER,  JSON.stringify(user));
    setAuth({ user, token: user.access_token, role: user.role as UserRole, isAuthenticated: true });
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY_TOKEN);
    localStorage.removeItem(STORAGE_KEY_USER);
    setAuth({ user: null, token: null, role: null, isAuthenticated: false });
  }, []);

  return (
    <AuthContext.Provider value={{ ...auth, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
