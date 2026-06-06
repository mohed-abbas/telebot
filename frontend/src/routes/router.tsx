// frontend/src/routes/router.tsx — the /app/* client router (react-router-dom 7, DECLARATIVE mode).
//
// D-07 / RESEARCH Pattern 4: createBrowserRouter + <RouterProvider> (declarative data router),
// NOT the framework/SSR mode. The `basename: "/app"` keeps the router in lockstep with the Vite
// `base: "/app/"` and the uvicorn StaticFiles mount (Pitfall 1/3) — so route paths are written
// WITHOUT the /app prefix and the basename adds it.
//
// Routes:
//   /login  → <LoginView/>                       (public; CSRF-seed on mount, no boot guard)
//   /       → <App/> (boot guard → <AppShell/>)  with an index child rendering the Overview
//             landing — the THROWAWAY <ProbeView/> from Task 2 (Phase 10 swaps in the real page).

import { createBrowserRouter } from "react-router-dom";

import App from "@/App";
import { LoginView } from "@/auth/LoginView";
import { AnalyticsView } from "@/routes/AnalyticsView";
import { ProbeView } from "@/routes/ProbeView";

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
          index: true,
          element: <ProbeView />,
        },
        {
          // PAGE-01 analytics pilot. Path written WITHOUT the /app prefix (basename adds it) →
          // reachable at /app/analytics. Index stays ProbeView (Overview is Phase 11; OQ2).
          path: "analytics",
          element: <AnalyticsView />,
        },
      ],
    },
  ],
  { basename: "/app" },
);
