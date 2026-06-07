// frontend/src/routes/router.tsx — the /app/* client router (react-router-dom 7, DECLARATIVE mode).
//
// D-07 / RESEARCH Pattern 4: createBrowserRouter + <RouterProvider> (declarative data router),
// NOT the framework/SSR mode. The `basename: "/app"` keeps the router in lockstep with the Vite
// `base: "/app/"` and the uvicorn StaticFiles mount (Pitfall 1/3) — so route paths are written
// WITHOUT the /app prefix and the basename adds it.
//
// Routes:
//   /login  → <LoginView/>                       (public; CSRF-seed on mount, no boot guard)
//   /       → <App/> (boot guard → <AppShell/>)  with an index child that RENDERS Overview
//             (Phase 11 — OQ2: Overview is now the live-money landing surface; the index no longer
//             redirects to the analytics pilot). The throwaway ProbeView is removed.

import { createBrowserRouter } from "react-router-dom";

import App from "@/App";
import { LoginView } from "@/auth/LoginView";
import { AnalyticsView } from "@/routes/AnalyticsView";
import { HistoryView } from "@/routes/HistoryView";
import { KillSwitchView } from "@/routes/KillSwitchView";
import { OverviewView } from "@/routes/OverviewView";
import { PositionsView } from "@/routes/PositionsView";
import { SettingsView } from "@/routes/SettingsView";
import { SignalsView } from "@/routes/SignalsView";
import { StagedView } from "@/routes/StagedView";

export const router = createBrowserRouter(
  [
    {
      path: "/login",
      element: <LoginView />,
    },
    {
      // App is the boot guard: it gates the shell on GET /api/v2/auth/me, then renders
      // <AppShell/> (which itself renders the routed <Outlet/>).
      path: "/",
      element: <App />,
      children: [
        {
          // Index landing: /app/ now resolves to Overview — the live-money landing surface (OQ2).
          // No longer a redirect to the analytics pilot.
          index: true,
          element: <OverviewView />,
        },
        {
          // PAGE-05 overview. Also reachable explicitly at /app/overview (basename adds the prefix);
          // the index above renders the same component so /app/ lands here.
          path: "overview",
          element: <OverviewView />,
        },
        {
          // PAGE-06 positions. Reachable at /app/positions (basename adds the prefix). 3s-polling
          // live-money table with per-row Close/Edit/drilldown.
          path: "positions",
          element: <PositionsView />,
        },
        {
          // PAGE-07 emergency kill switch. Reachable at /app/emergency (the Overview entry button
          // navigates here). Two-step preview→CONFIRM CLOSE ALL flow.
          path: "emergency",
          element: <KillSwitchView />,
        },
        {
          // PAGE-01 analytics pilot. Path written WITHOUT the /app prefix (basename adds it) →
          // reachable at /app/analytics.
          path: "analytics",
          element: <AnalyticsView />,
        },
        {
          // PAGE-02 signal log. Reachable at /app/signals (basename adds the prefix).
          path: "signals",
          element: <SignalsView />,
        },
        {
          // PAGE-03 trade history. Reachable at /app/history (basename adds the prefix).
          path: "history",
          element: <HistoryView />,
        },
        {
          // PAGE-04 pending stages. Reachable at /app/stages (basename adds the prefix). The only
          // background-polling page (D-07).
          path: "stages",
          element: <StagedView />,
        },
        {
          // PAGE-08 per-account settings. Reachable at /app/settings (basename adds the prefix).
          // The two-step validate→confirm-diff→confirm flow (D-05); does not poll.
          path: "settings",
          element: <SettingsView />,
        },
      ],
    },
  ],
  { basename: "/app" },
);
