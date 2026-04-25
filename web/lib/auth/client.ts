/**
 * Thin wrappers around the auth API endpoints.
 *
 * All calls go through the Next.js proxy (/api/proxy/*) so the browser
 * never talks directly to port 8000.  Cookies (aegis_access / aegis_refresh)
 * are httpOnly and managed by the browser automatically — we never touch them
 * from JS.
 */

const BASE = "/api/proxy";

// ---------------------------------------------------------------------------
// Shared response types
// ---------------------------------------------------------------------------

export interface AuthTenant {
  id: string;
  slug: string;
  name: string;
  plan: string;
}

export interface AuthUser {
  id: string;
  email: string;
  display_name: string | null;
  role: "owner" | "admin" | "member";
  tenant: AuthTenant | null;
}

// ---------------------------------------------------------------------------
// GET /auth/me — check session / fetch current user
// ---------------------------------------------------------------------------

export async function getMe(): Promise<AuthUser | null> {
  try {
    const res = await fetch(`${BASE}/auth/me`, {
      credentials: "include",
      cache: "no-store",
    });
    if (!res.ok) return null;
    return res.json() as Promise<AuthUser>;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// POST /auth/login
// ---------------------------------------------------------------------------

export async function login(email: string, password: string): Promise<AuthUser> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(data.detail ?? "Login failed");
  }
  const data = await res.json() as { user: AuthUser };
  return data.user;
}

// ---------------------------------------------------------------------------
// POST /auth/logout
// ---------------------------------------------------------------------------

export async function logout(): Promise<void> {
  await fetch(`${BASE}/auth/logout`, {
    method: "POST",
    credentials: "include",
  }).catch(() => {/* best-effort */});
}

// ---------------------------------------------------------------------------
// POST /auth/register
// ---------------------------------------------------------------------------

export interface RegisterPayload {
  email: string;
  password: string;
  tenant_name: string;
  display_name?: string;
}

export async function register(payload: RegisterPayload): Promise<AuthUser> {
  const res = await fetch(`${BASE}/auth/register`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(data.detail ?? "Registration failed");
  }
  const data = await res.json() as { user: AuthUser };
  return data.user;
}

// ---------------------------------------------------------------------------
// POST /auth/accept-invite/{token}
// ---------------------------------------------------------------------------

export async function acceptInvite(
  token: string,
  password: string,
  display_name?: string,
): Promise<AuthUser> {
  const res = await fetch(`${BASE}/auth/accept-invite/${token}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password, display_name }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(data.detail ?? "Invalid invite");
  }
  const data = await res.json() as { user: AuthUser };
  return data.user;
}
