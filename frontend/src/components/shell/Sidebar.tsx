// frontend/src/components/shell/Sidebar.tsx — the 224px app-shell sidebar + nav skeleton (D-07).
//
// Mirrors templates/base.html EXACT labels so the parallel-run HTMX↔SPA stays legible:
//   Wordmark "Telebot" (text-primary cyan) + "Trading Dashboard" subtitle (muted-foreground)
//   Live links:       "Overview", "Trade History", "Signal Log", "Analytics" (Phase 10 read-only pages)
//   Disabled-visible: Positions, Pending Stages, Settings
//                     (muted-foreground, non-interactive, NOT hidden — enabled in place as pages ship)
//   Footer:           "Sign out" → POST /api/v2/auth/logout (http wrapper adds X-CSRF-Token; T-09-12)
//
// UI-SPEC §Color (focal point): the cyan --primary accent is RESERVED for the wordmark, the ACTIVE
// nav indicator, and focus rings ONLY. Disabled links use muted-foreground — never the accent.
// Nav rows are min-h-10 (40px) tap targets (UI-SPEC §Spacing).

import { NavLink } from "react-router-dom";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { api } from "@/lib/http";

// Nav entries in legacy order. A `to` ⇒ a live <NavLink>; otherwise a disabled-visible <span>.
// Phase 10 enables the read-only pages in place: Analytics (Plan 04), Trade History + Signal Log
// (Plan 05), Pending Stages (Plan 06, this wave). Live-money pages (Positions, Settings) land in
// Phase 11 and stay disabled-visible spans. Each `to:` below renders as an active NavLink via the
// generic branch.
type NavEntry = { label: string; to?: string; end?: boolean };

const NAV_ENTRIES: readonly NavEntry[] = [
  { label: "Overview", to: "/", end: true },
  { label: "Positions" },
  { label: "Trade History", to: "/history" },
  { label: "Signal Log", to: "/signals" },
  { label: "Analytics", to: "/analytics" },
  { label: "Pending Stages", to: "/stages" },
  { label: "Settings" },
] as const;

const navRowBase =
  "flex min-h-10 items-center rounded-md px-3 text-sm transition-colors";

// Active-link className builder, shared by the data-driven map below. The cyan --primary accent
// is RESERVED for the active indicator + focus ring (UI-SPEC §Color).
const liveLinkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    navRowBase,
    "outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
    isActive
      ? "bg-sidebar-accent font-medium text-primary"
      : "text-sidebar-foreground hover:bg-sidebar-accent",
  );

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

// `onNavigate` lets the mobile app-shell close its drawer when a nav link is tapped.
// Scoped to NavLinks only — NOT the Sign-out button (which hard-navigates), so the
// drawer-close never races the async logout handler (WR-06).
export function Sidebar({ onNavigate }: { onNavigate?: () => void } = {}) {
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
          {NAV_ENTRIES.map((entry) => {
            // Analytics is the page this plan (PAGE-01) makes live — render the explicit
            // active NavLink to="/analytics" copied from the Overview analog.
            if (entry.label === "Analytics") {
              return (
                <li key={entry.label}>
                  <NavLink to="/analytics" className={liveLinkClass} onClick={onNavigate}>
                    {entry.label}
                  </NavLink>
                </li>
              );
            }
            // Any other entry with a `to` is also a live NavLink (e.g. Overview).
            if (entry.to) {
              return (
                <li key={entry.label}>
                  <NavLink to={entry.to} end={entry.end} className={liveLinkClass} onClick={onNavigate}>
                    {entry.label}
                  </NavLink>
                </li>
              );
            }
            // Disabled-visible future link — muted-foreground, non-interactive, NOT hidden.
            return (
              <li key={entry.label}>
                <span
                  aria-disabled="true"
                  className={cn(
                    navRowBase,
                    "cursor-not-allowed text-muted-foreground select-none",
                  )}
                >
                  {entry.label}
                </span>
              </li>
            );
          })}
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
