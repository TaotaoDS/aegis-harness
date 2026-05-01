/**
 * Global fetch interceptor that detects X-Auth-Expired: true responses from
 * the Next.js proxy and fires a custom DOM event so AuthProvider can surface
 * the SessionExpiredModal without needing to thread a callback through every
 * fetch call site.
 *
 * Call installSessionGuard() once (inside AuthProvider's useEffect) to
 * activate — it replaces window.fetch with a thin wrapper.
 * Call uninstallSessionGuard() on unmount to restore the original.
 */

const EVENT_NAME = "aegis:session-expired";

let _original: typeof fetch | null = null;

export function installSessionGuard(): void {
  if (typeof window === "undefined" || _original !== null) return;
  _original = window.fetch;

  window.fetch = async function patchedFetch(
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> {
    const res = await _original!(input, init);
    if (res.status === 401 && res.headers.get("X-Auth-Expired") === "true") {
      window.dispatchEvent(new CustomEvent(EVENT_NAME));
    }
    return res;
  };
}

export function uninstallSessionGuard(): void {
  if (typeof window === "undefined" || _original === null) return;
  window.fetch = _original;
  _original = null;
}

export { EVENT_NAME as SESSION_EXPIRED_EVENT };
