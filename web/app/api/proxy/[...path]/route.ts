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
 * SSE streams (text/event-stream) are passed through without buffering
 * because we hand upstream.body (ReadableStream) directly to NextResponse.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

type Params = { path: string[] };

async function proxy(
  req: NextRequest,
  context: { params: Promise<Params> },
) {
  const { path } = await context.params;
  const search = req.nextUrl.search;
  const target = `${BACKEND}/${path.join("/")}${search}`;

  // Forward all request headers except host; this includes the Cookie header
  // so the backend receives aegis_access / aegis_refresh on every call.
  const outHeaders = new Headers(req.headers);
  outHeaders.delete("host");

  const init: RequestInit & { duplex?: string } = {
    method: req.method,
    headers: outHeaders,
    // Required by Node.js 18+ for streaming request bodies
    ...(req.method !== "GET" && req.method !== "HEAD"
      ? { body: req.body, duplex: "half" }
      : {}),
    // Never let Next.js cache the upstream response
    cache: "no-store",
  };

  let upstream: Response;
  try {
    upstream = await fetch(target, init as RequestInit);
  } catch (err) {
    return NextResponse.json(
      { detail: `Backend unreachable: ${String(err)}` },
      { status: 502 },
    );
  }

  // Build response headers, forwarding Set-Cookie individually so that
  // multiple cookies (e.g. aegis_access + aegis_refresh) are never merged.
  const resHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (key.toLowerCase() === "set-cookie") {
      resHeaders.append("set-cookie", value);
    } else {
      resHeaders.set(key, value);
    }
  });

  // Pass body (ReadableStream) through unchanged — works for both JSON and SSE
  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: resHeaders,
  });
}

export const GET     = proxy;
export const POST    = proxy;
export const PUT     = proxy;
export const PATCH   = proxy;
export const DELETE  = proxy;
