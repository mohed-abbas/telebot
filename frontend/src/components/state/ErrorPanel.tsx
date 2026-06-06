// frontend/src/components/state/ErrorPanel.tsx — inline error + Retry (D-11).
//
// An INLINE panel in the page body — NOT a sonner toast. Toasts (sonner) stay reserved for
// ACTION feedback (Sidebar.tsx logout failure, Phase 11 mutations). A failed READ leaves a
// visible, retryable failure state in place of the body.
//
// The message is read from `HttpError.body` — the `{error:{code,message}}` envelope produced by
// api/errors.py (http.ts:64) — falling back to a generic string. `401` never reaches this panel:
// the inherited global onAuthError (queryClient.ts) hard-navigates to /app/login?expired=1 first,
// so a 401 is redirected before any page's isError branch renders.
//
// NOTE: this file intentionally does NOT import `toast` from sonner (D-11 — inline, not toast).

import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { HttpError } from "@/lib/http";
import { cn } from "@/lib/utils";

const FALLBACK_MESSAGE = "Something went wrong loading this page.";

interface ErrorEnvelope {
  error?: { code?: string; message?: string };
}

/** Extract a human message from an HttpError envelope, falling back to a generic string. */
export function errorMessage(error: unknown): string {
  if (error instanceof HttpError) {
    const body = error.body as ErrorEnvelope | undefined;
    const msg = body?.error?.message;
    if (typeof msg === "string" && msg.trim()) return msg;
    return `Request failed (HTTP ${error.status}).`;
  }
  if (error instanceof Error && error.message.trim()) return error.message;
  return FALLBACK_MESSAGE;
}

export interface ErrorPanelProps {
  /** The thrown error (typically an HttpError) — used to derive the message. */
  error?: unknown;
  /** Explicit message override; otherwise derived from `error`. */
  message?: string;
  /** Retry callback — wired to a query's `refetch`. */
  onRetry?: () => void;
  className?: string;
}

export function ErrorPanel({
  error,
  message,
  onRetry,
  className,
}: ErrorPanelProps) {
  const text = message ?? errorMessage(error);
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-destructive/40 bg-card px-6 py-10 text-center",
        className,
      )}
    >
      <AlertTriangle aria-hidden="true" className="size-8 text-destructive" />
      <p className="text-sm font-medium text-card-foreground">{text}</p>
      {onRetry ? (
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}
