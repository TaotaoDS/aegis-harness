/**
 * Catch-all reverse proxy for FastAPI backend (port 8000).
 *
 * All paths under /api/proxy/** are forwarded to the backend, eliminating
 * CORS issues entirely — the browser only ever talks to port 3000.
 *
 * Cookie handling
 * ---------------
 * • Request:  the browser's Cookie header is forwarded as-is so httpOnly
 *   tokens (aegis_access / aegis_refresh) reach the backend on every call.
 * • Response: Set-Cookie headers from the backend are copied one-by-one so
 *   multiple cookies (access + refresh) are never silently collapsed by the
 *   Node.js Headers implementation.
 *
 * 401 → refresh → retry
 * ----------------------
 * When the backend returns 401, the proxy automatically attempts a token
 * refresh (POST /auth/refresh with the same cookies).  On success the
 * original request is retried once with the refreshed cookies.  If the
 * refresh also fails a 401 is returned with the header X-Auth-Expired: true
 * so the client can show a "session expired" modal without a page reload.
 *
 * SSE streams (text/event-stream) are passed through without buffering
 * because we hand upstream.body (ReadableStream) directly to NextResponse.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

type Params = { path: string[] };

/** Extract `name=value` pairs from Set-Cookie headers, ignoring directives. */
function parseCookiesFromSetCookie(setCookieHeaders: string[]): string {
  return setCookieHeaders
    .map((h) => h.split(";")[0].trim())   // keep only "name=value"
    .join("; ");
}

/** Merge new cookies into an existing Cookie header string. */
function mergeCookies(existing: string, incoming: string): string {
  if (!existing) return incoming;
  if (!incoming) return existing;

  const existingMap = new Map<string, string>();
  for (const pair of existing.split(";")) {
    const eqIdx = pair.indexOf("=");
    if (eqIdx === -1) continue;
    existingMap.set(pair.slice(0, eqIdx).trim(), pair.slice(eqIdx + 1).trim());
  }
  for (const pair of incoming.split(";")) {
    const eqIdx = pair.indexOf("=");
    if (eqIdx === -1) continue;
    existingMap.set(pair.slice(0, eqIdx).trim(), pair.slice(eqIdx + 1).trim());
  }
  return [...existingMap.entries()].map(([k, v]) => `${k}=${v}`).join("; ");
}

/** Copy all response headers, appending Set-Cookie individually. */
function buildResHeaders(upstream: Response): Headers {
  const resHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (key.toLowerCase() === "set-cookie") {
      resHeaders.append("set-cookie", value);
    } else {
      resHeaders.set(key, value);
    }
  });
  return resHeaders;
}

async function proxy(
  req: NextRequest,
  context: { params: Promise<Params> },
) {
  const { path } = await context.params;
  const search = req.nextUrl.search;
  const target = `${BACKEND}/${path.join("/")}${search}`;

  const isBodyMethod = req.method !== "GET" && req.method !== "HEAD";

  // Buffer the request body once so we can replay it on retry.
  // For SSE/streaming GET paths this is a no-op (body is null).
  const bodyBuffer: ArrayBuffer | null = isBodyMethod
    ? await req.arrayBuffer()
    : null;

  const makeInit = (cookieOverride?: string): RequestInit & { duplex?: string } => {
    const outHeaders = new Headers(req.headers);
    outHeaders.delete("host");
    if (cookieOverride) outHeaders.set("cookie", cookieOverride);

    return {
      method: req.method,
      headers: outHeaders,
      ...(isBodyMethod && bodyBuffer !== null
        ? { body: bodyBuffer, duplex: "half" }
        : {}),
      cache: "no-store",
    };
  };

  // ── First attempt ────────────────────────────────────────────────────────
  let upstream: Response;
  try {
    upstream = await fetch(target, makeInit() as RequestInit);
  } catch (err) {
    return NextResponse.json(
      { detail: `Backend unreachable: ${String(err)}` },
      { status: 502 },
    );
  }

  // Happy path — forward immediately (includes SSE streams)
  if (upstream.status !== 401) {
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: buildResHeaders(upstream),
    });
  }

  // ── 401 received — attempt token refresh ─────────────────────────────────
  const existingCookie = req.headers.get("cookie") ?? "";

  let refreshRes: Response;
  try {
    refreshRes = await fetch(`${BACKEND}/auth/refresh`, {
      method: "POST",
      headers: { cookie: existingCookie },
      cache:   "no-store",
    });
  } catch {
    // Backend unreachable during refresh — return original 401
    const h = buildResHeaders(upstream);
    h.set("X-Auth-Expired", "true");
    return new NextResponse(null, { status: 401, headers: h });
  }

  if (!refreshRes.ok) {
    // Refresh failed (likely expired refresh token) — signal client
    const h = buildResHeaders(upstream);
    h.set("X-Auth-Expired", "true");
    return new NextResponse(null, { status: 401, headers: h });
  }

  // Refresh succeeded — extract new cookies and retry original request
  const newSetCookies: string[] = [];
  refreshRes.headers.forEach((value, key) => {
    if (key.toLowerCase() === "set-cookie") newSetCookies.push(value);
  });
  const newCookieStr = parseCookiesFromSetCookie(newSetCookies);
  const mergedCookie = mergeCookies(existingCookie, newCookieStr);

  // ── Retry original request with refreshed cookies ────────────────────────
  let retried: Response;
  try {
    retried = await fetch(target, makeInit(mergedCookie) as RequestInit);
  } catch (err) {
    return NextResponse.json(
      { detail: `Backend unreachable on retry: ${String(err)}` },
      { status: 502 },
    );
  }

  // Forward new token cookies alongside the retried response headers
  const resHeaders = buildResHeaders(retried);
  for (const sc of newSetCookies) {
    resHeaders.append("set-cookie", sc);
  }

  return new NextResponse(retried.body, {
    status: retried.status,
    headers: resHeaders,
  });
}

export const GET     = proxy;
export const POST    = proxy;
export const PUT     = proxy;
export const PATCH   = proxy;
export const DELETE  = proxy;
