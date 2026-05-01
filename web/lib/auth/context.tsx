"use client";

/**
 * AuthProvider + useAuth() hook.
 *
 * On mount the provider calls GET /auth/me to hydrate the session.
 * In DEV_MODE the backend always returns a synthetic user, so the
 * frontend never redirects to /login during local development.
 *
 * Exported helpers (login / logout) update the in-memory user state
 * after every auth action so consumers re-render without a page reload.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { getMe, login as apiLogin, logout as apiLogout } from "./client";
import { installSessionGuard, uninstallSessionGuard, SESSION_EXPIRED_EVENT } from "./sessionGuard";
import type { AuthUser } from "./client";

// ---------------------------------------------------------------------------
// Context shape
// ---------------------------------------------------------------------------

interface AuthContextValue {
  /** null = not authenticated (or still loading) */
  user: AuthUser | null;
  /** true while the initial /auth/me call is in flight */
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Re-fetch the current user (e.g. after an invite accept) */
  refresh: () => Promise<void>;
  /** true when the proxy detected an expired session (X-Auth-Expired: true) */
  sessionExpired: boolean;
  /** Call after successful re-login to dismiss the SessionExpiredModal */
  clearSessionExpired: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user,           setUser]           = useState<AuthUser | null>(null);
  const [loading,        setLoading]        = useState(true);
  const [sessionExpired, setSessionExpired] = useState(false);

  const refresh = useCallback(async () => {
    const me = await getMe();
    setUser(me);
  }, []);

  // Hydrate on first mount + install global fetch guard
  useEffect(() => {
    getMe()
      .then(setUser)
      .finally(() => setLoading(false));

    installSessionGuard();
    const handler = () => setSessionExpired(true);
    window.addEventListener(SESSION_EXPIRED_EVENT, handler);
    return () => {
      window.removeEventListener(SESSION_EXPIRED_EVENT, handler);
      uninstallSessionGuard();
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const me = await apiLogin(email, password);
    setUser(me);
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  const clearSessionExpired = useCallback(() => setSessionExpired(false), []);

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refresh, sessionExpired, clearSessionExpired }}>
      {children}
    </AuthContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth() must be used inside <AuthProvider>");
  }
  return ctx;
}
