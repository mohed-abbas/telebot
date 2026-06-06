// frontend/src/lib/http.ts — the single fetch wrapper every queryFn/mutationFn uses.
//
// Consumes the Phase 8 /api/v2 JSON contract (api/auth.py, api/deps.py, api/errors.py):
//   - Double-submit CSRF (D-04 / D-15): echo the readable `telebot_csrf` cookie as the
//     `X-CSRF-Token` header on state-changing methods ONLY (POST/PUT/PATCH/DELETE), matching
//     api/deps.py `_STATE_CHANGING_METHODS`. GET et al. pass through untouched.
//   - `credentials: "same-origin"` (D-04): the browser attaches the httpOnly session cookie
//     automatically. JS never reads that httpOnly session cookie; no auth token is ever written
//     to browser storage (SPA-03 / T-09-06).
//   - On any non-2xx, throw `HttpError(status, body)` (D-06 / T-09-07) so BOTH the QueryCache
//     and MutationCache `onError` see 401s (queryClient.ts wires the single global handler).
//   - Relative `/api/v2/...` URLs only — never absolute http://localhost:8090 (T-09-09):
//     same-origin via the dev proxy + prod nginx keeps the cookie attached.

export class HttpError extends Error {
  readonly status: number;
  readonly body?: unknown;

  constructor(status: number, body?: unknown) {
    super(`HTTP ${status}`);
    this.name = "HttpError";
    this.status = status;
    this.body = body;
  }
}

const STATE_CHANGING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/**
 * Read a readable (non-httpOnly) cookie value from document.cookie.
 * Used for the readable `telebot_csrf` cookie only — the httpOnly session cookie
 * is invisible to JS by design and is never read here.
 */
export function readCookie(name: string): string {
  const prefix = name + "=";
  const match = document.cookie
    .split("; ")
    .find((c) => c.startsWith(prefix));
  return match ? decodeURIComponent(match.slice(prefix.length)) : "";
}

/**
 * The one fetch path for the whole SPA. Echoes CSRF on mutations, sends the
 * same-origin session cookie, and throws HttpError on non-2xx.
 */
export async function api(path: string, init: RequestInit = {}): Promise<unknown> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);

  // D-04 / D-15: echo the readable telebot_csrf cookie on mutating methods only.
  if (STATE_CHANGING_METHODS.has(method)) {
    headers.set("X-CSRF-Token", readCookie("telebot_csrf"));
  }

  const res = await fetch(path, {
    ...init,
    headers,
    credentials: "same-origin", // D-04: attach the httpOnly session cookie; never read it in JS
  });

  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json(); // {error:{code,message,fields?}} envelope from api/errors.py
    } catch {
      /* non-JSON / empty body — tolerate */
    }
    throw new HttpError(res.status, body);
  }

  // 204 No Content has no JSON body.
  if (res.status === 204) return null;
  return res.json();
}
