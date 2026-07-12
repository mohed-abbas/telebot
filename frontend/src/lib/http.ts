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
//   - §2.1 self-heal: if a mutation 403s because the telebot_csrf cookie is missing/stale (the
//     enveloped message contains "CSRF"), reseed the cookie ONCE via seedCsrf() and retry the
//     request exactly once. A device that auto-authenticates off the persistent session cookie
//     after a browser restart may have no CSRF cookie; this recovers it transparently.

import { seedCsrf } from "@/auth/csrf";

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

/** True when a non-2xx body is the enveloped CSRF-rejection from api/deps.verify_csrf_token. */
function isCsrfError(status: number, body: unknown): boolean {
  if (status !== 403) return false;
  const message = (body as { error?: { message?: string } } | undefined)?.error?.message;
  return typeof message === "string" && message.includes("CSRF");
}

/**
 * The one fetch path for the whole SPA. Echoes CSRF on mutations, sends the
 * same-origin session cookie, and throws HttpError on non-2xx.
 *
 * `_retried` is internal: it guards the §2.1 CSRF self-heal so a request is
 * reseeded-and-retried at most once (never an infinite loop).
 */
export async function api(
  path: string,
  init: RequestInit = {},
  _retried = false,
): Promise<unknown> {
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
    // §2.1 self-heal: a missing/stale CSRF cookie yields a 403 "CSRF ..." envelope. Reseed the
    // cookie once (GET /auth/csrf is not a mutation, so it cannot itself CSRF-403) and retry the
    // original request exactly once; if it still fails, propagate.
    if (!_retried && isCsrfError(res.status, body)) {
      await seedCsrf();
      return api(path, init, true);
    }
    throw new HttpError(res.status, body);
  }

  // 204 No Content has no JSON body.
  if (res.status === 204) return null;
  return res.json();
}
