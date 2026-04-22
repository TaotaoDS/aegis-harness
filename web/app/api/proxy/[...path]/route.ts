/**
 * Catch-all reverse proxy for FastAPI backend (port 8000).
 *
 * All paths under /api/proxy/** are forwarded to the backend, eliminating
 * CORS issues entirely — the browser only ever talks to port 3000.
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

  // Forward all headers except host
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

  // Pass body (ReadableStream) through unchanged — works for both JSON and SSE
  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: upstream.headers,
  });
}

export const GET     = proxy;
export const POST    = proxy;
export const PUT     = proxy;
export const PATCH   = proxy;
export const DELETE  = proxy;
