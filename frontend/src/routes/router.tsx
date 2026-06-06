// frontend/src/routes/router.tsx — the /app/* client router (react-router-dom 7, DECLARATIVE mode).
//
// D-07 / RESEARCH Pattern 4: createBrowserRouter + <RouterProvider> (declarative data router),
// NOT the framework/SSR mode. The `basename: "/app"` keeps the router in lockstep with the Vite
// `base: "/app/"` and the uvicorn StaticFiles mount (Pitfall 1/3) — so route paths are written
// WITHOUT the /app prefix and the basename adds it.
//
// Routes:
//   /login  → <LoginView/>                       (public; CSRF-seed on mount, no boot guard)
//   /       → <App/> (boot guard → <AppShell/>)  with an index child that REDIRECTS to the
//             analytics pilot (Overview is Phase 11 — OQ2). The throwaway ProbeView is removed.

import { Navigate, createBrowserRouter } from "react-router-dom";

import App from "@/App";
import { LoginView } from "@/auth/LoginView";
import { AnalyticsView } from "@/routes/AnalyticsView";
import { HistoryView } from "@/routes/HistoryView";
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
          // Index landing: redirect /app/ to the shipped analytics pilot (Overview is Phase 11 —
          // OQ2). `replace` keeps /app/ out of the history stack so Back doesn't bounce.
          index: true,
          element: <Navigate to="/analytics" replace />,
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
      ],
    },
  ],
  { basename: "/app" },
);
