// frontend/src/components/shell/Sidebar.tsx — the 224px app-shell sidebar + nav skeleton (D-07).
//
// Mirrors templates/base.html EXACT labels so the parallel-run HTMX↔SPA stays legible:
//   Wordmark "Telebot" (text-primary cyan) + "Trading Dashboard" subtitle (muted-foreground)
//   Live link:        "Overview"  (the landing route; hosts the throwaway probe)
//   Disabled-visible: Positions, Trade History, Signal Log, Analytics, Pending Stages, Settings
//                     (muted-foreground, non-interactive, NOT hidden — Phase 10 enables in place)
//   Footer:           "Sign out" → POST /api/v2/auth/logout (http wrapper adds X-CSRF-Token; T-09-12)
//
// UI-SPEC §Color (focal point): the cyan --primary accent is RESERVED for the wordmark, the ACTIVE
// nav indicator, and focus rings ONLY. Disabled links use muted-foreground — never the accent.
// Nav rows are min-h-10 (40px) tap targets (UI-SPEC §Spacing).

import { NavLink } from "react-router-dom";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { api } from "@/lib/http";

/** Future pages, enabled in place by Phase 10. Rendered disabled-visible (not hidden). */
const FUTURE_LINKS = [
  "Positions",
  "Trade History",
  "Signal Log",
  "Analytics",
  "Pending Stages",
  "Settings",
] as const;

async function signOut() {
  // WR-02: the httpOnly session cookie is cleared SERVER-SIDE by the logout route.
  // If the POST fails (403 CSRF mismatch, network, 500) the cookie still exists —
  // so navigating to login anyway would land the user on the login view while the
  // session is still valid ("I logged out but I'm still in"). Only redirect on a
  // confirmed server-side clear; on failure surface the error and let the user
  // retry instead of pretending success.
  try {
    // The only POST in Phase 9. The http wrapper sets X-CSRF-Token from the readable cookie.
    await api("/api/v2/auth/logout", { method: "POST" });
  } catch (err) {
    console.error("Sign out failed; session may still be active:", err);
    toast.error("Sign out failed. Please try again.");
    return;
  }
  // Confirmed logged out (2xx): hard-nav to login, clearing in-memory state.
  window.location.assign("/app/login");
}

const navRowBase =
  "flex min-h-10 items-center rounded-md px-3 text-sm transition-colors";

export function Sidebar() {
  return (
    <nav
      aria-label="Main navigation"
      className="flex h-full w-56 flex-col bg-sidebar text-sidebar-foreground"
    >
      {/* Brand header — the cyan wordmark is the one saturated element up here. */}
      <div className="border-b border-sidebar-border p-4">
        <h1 className="text-lg font-bold text-primary">Telebot</h1>
        <p className="mt-1 text-xs text-muted-foreground">Trading Dashboard</p>
      </div>

      {/* Nav skeleton */}
      <div className="flex-1 overflow-y-auto py-2">
        <ul className="flex flex-col gap-0.5 px-2">
          {/* Live: Overview. Active indicator = cyan accent (reserved). */}
          <li>
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                cn(
                  navRowBase,
                  "outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
                  isActive
                    ? "bg-sidebar-accent font-medium text-primary"
                    : "text-sidebar-foreground hover:bg-sidebar-accent",
                )
              }
            >
              Overview
            </NavLink>
          </li>

          {/* Disabled-visible future links — muted-foreground, non-interactive, NOT hidden. */}
          {FUTURE_LINKS.map((label) => (
            <li key={label}>
              <span
                aria-disabled="true"
                className={cn(
                  navRowBase,
                  "cursor-not-allowed text-muted-foreground select-none",
                )}
              >
                {label}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {/* Footer: Sign out (the only Phase-9 mutation). */}
      <div className="border-t border-sidebar-border p-2">
        <button
          type="button"
          onClick={signOut}
          className={cn(
            navRowBase,
            "w-full text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
          )}
        >
          Sign out
        </button>
      </div>
    </nav>
  );
}
