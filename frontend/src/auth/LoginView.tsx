// frontend/src/auth/LoginView.tsx — the SPA login view (SPA-03).
//
// Consumes the Phase 8 contract (api/auth.py): seeds the readable telebot_csrf cookie on mount
// (cold-start guard, Pitfall 5), then POSTs login. The http wrapper supplies X-CSRF-Token from the
// cookie; the body echoes the same token (csrf_token). The backend LoginIn schema takes
// {password, csrf_token} only — Username is rendered for UI parity (UI-SPEC) but NOT submitted.
//
// State discipline (SC#5): inputs are local React state only; there is no server cache here.
//
// UI-SPEC: centered --card (#1a1a2e) on the --background (#0f0f1a) field; "Telebot" Display
// 28px/600 title; "Username"/"Password" labels; the cyan --primary "Log in" CTA is the ONLY
// saturated element (color focal point). Copy is verbatim from the UI-SPEC copywriting contract.

import { type FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { HttpError, api } from "@/lib/http";
import { readCsrfCookie, seedCsrf } from "@/auth/csrf";

const ERROR_BAD_CREDENTIALS = "Incorrect username or password.";
const ERROR_GENERIC = "Something went wrong. Please try again.";
const SESSION_EXPIRED_BANNER = "Your session expired — please log in again.";

/** Show the session-expired banner only when arrived via a 401 redirect flag. */
function arrivedViaSessionExpiry(): boolean {
  const params = new URLSearchParams(window.location.search);
  return params.has("expired") || params.get("reason") === "expired";
}

export function LoginView() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionExpired = arrivedViaSessionExpiry();

  // Cold-start guard (Pitfall 5): seed the readable telebot_csrf cookie before any login.
  useEffect(() => {
    void seedCsrf().catch(() => {
      /* seeding failures surface on submit as the generic error; nothing to store */
    });
  }, []);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      await api("/api/v2/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // Backend LoginIn = {password, csrf_token}. The http wrapper adds X-CSRF-Token.
        body: JSON.stringify({ password, csrf_token: readCsrfCookie() }),
      });
      // Success: the server set the httpOnly session cookie. Hard-nav into the app shell
      // (the router/boot-guard gate lands in Plan 04).
      window.location.assign("/app/");
    } catch (err) {
      if (err instanceof HttpError && err.status === 401) {
        setError(ERROR_BAD_CREDENTIALS);
      } else {
        // 403 cold-start / 429 / 500 / network — no field-specific leak.
        setError(ERROR_GENERIC);
      }
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-6">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          {/* Display 28px/600 — the brand title */}
          <CardTitle className="text-[28px] font-semibold leading-tight">
            Telebot
          </CardTitle>
        </CardHeader>
        <CardContent>
          {sessionExpired && (
            <div
              role="status"
              className="mb-4 rounded-md border border-border bg-muted px-3 py-2 text-sm text-muted-foreground"
            >
              {SESSION_EXPIRED_BANNER}
            </div>
          )}
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                name="username"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={pending}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={pending}
              />
            </div>
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            {/* The cyan --primary CTA — the ONLY saturated element in this view. */}
            <Button type="submit" disabled={pending} className="w-full">
              {pending ? "Logging in…" : "Log in"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
