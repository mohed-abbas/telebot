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
  try {
    // The only POST in Phase 9. The http wrapper sets X-CSRF-Token from the readable cookie.
    await api("/api/v2/auth/logout", { method: "POST" });
  } catch {
    /* Even if logout errors, fall through to the hard-nav: clears in-memory state regardless. */
  } finally {
    window.location.assign("/app/login");
  }
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
