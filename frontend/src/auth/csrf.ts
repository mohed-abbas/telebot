// frontend/src/auth/csrf.ts — cold-start CSRF seeding (RESEARCH Pitfall 5).
//
// The Phase 8 login (api/auth.py:login) requires BOTH a `csrf_token` in the JSON body AND a
// matching readable `telebot_csrf` cookie (compared with secrets.compare_digest). On a cold first
// visit there is no cookie yet, so the login view MUST call `GET /api/v2/auth/csrf` on mount —
// it seeds the readable cookie AND returns the identical token in the body — BEFORE the first
// `POST /auth/login`, or the login 403s ("CSRF token invalid").

import { api, readCookie } from "@/lib/http";

const CSRF_COOKIE = "telebot_csrf";

interface CsrfResponse {
  csrf_token: string;
}

/** Read the readable `telebot_csrf` cookie (the value echoed in the login body + header). */
export function readCsrfCookie(): string {
  return readCookie(CSRF_COOKIE);
}

/**
 * Seed the readable `telebot_csrf` cookie via GET /api/v2/auth/csrf and return the token.
 * Must run on the login view's mount before the first login (cold-start guard).
 */
export async function seedCsrf(): Promise<string> {
  const data = (await api("/api/v2/auth/csrf")) as CsrfResponse;
  return data.csrf_token;
}
