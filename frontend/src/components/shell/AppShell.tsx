// frontend/src/components/shell/AppShell.tsx — the protected app shell layout (D-07).
//
// Layout (UI-SPEC §Spacing):
//   - Sidebar fixed 224px (w-56). On md+ it is permanently visible (fixed left); the main content
//     is offset md:ml-56. Below md the sidebar is a drawer, hidden by default and toggled open by
//     the top-bar button (mirrors templates/base.html's mobile header behavior).
//   - <Outlet/> renders the routed content (the four Phase-10 read-only pages; /app/ redirects to
//     the analytics pilot until the Phase-11 Overview lands).
//
// This is rendered ONLY after App.tsx's boot guard resolves 200 (T-09-10): the shell never paints
// before auth is confirmed.

import { useState } from "react";
import { Menu, X } from "lucide-react";
import { Outlet } from "react-router-dom";

import { Sidebar } from "@/components/shell/Sidebar";
import { cn } from "@/lib/utils";

export function AppShell() {
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="min-h-svh bg-background text-foreground">
      {/* Mobile top bar (below md): the drawer toggle. */}
      <header className="fixed inset-x-0 top-0 z-30 flex h-12 items-center border-b border-sidebar-border bg-sidebar px-4 md:hidden">
        <button
          type="button"
          aria-label={drawerOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={drawerOpen}
          onClick={() => setDrawerOpen((v) => !v)}
          className="-ml-2 inline-flex size-9 items-center justify-center rounded-md text-foreground outline-none hover:bg-sidebar-accent focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          {drawerOpen ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
        <span className="ml-3 text-sm font-semibold">Telebot</span>
      </header>

      {/* Backdrop (mobile drawer only) */}
      {drawerOpen && (
        <div
          aria-hidden="true"
          onClick={() => setDrawerOpen(false)}
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
        />
      )}

      {/* Sidebar: fixed drawer on mobile (slides in), fixed rail on md+. */}
      <div
        className={cn(
          "fixed inset-y-0 left-0 z-40 transition-transform duration-200 md:translate-x-0",
          drawerOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0",
        )}
        onClick={() => setDrawerOpen(false)}
      >
        <Sidebar />
      </div>

      {/* Main content — offset by the 224px rail on md+, padded under the mobile top bar. */}
      <main className="min-h-svh px-4 pt-12 md:ml-56 md:px-6 md:pt-6">
        <Outlet />
      </main>
    </div>
  );
}
