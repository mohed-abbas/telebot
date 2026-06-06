// frontend/src/App.tsx — the boot guard that gates the protected app shell (D-05 / SPA-04).
//
// On mount it resolves auth via GET /api/v2/auth/me (the lightest server-side session check):
//   - 200 {"user":...}  → render the protected <AppShell/> (which renders the routed <Outlet/>).
//   - 401               → the SINGLE global onAuthError (queryClient.ts) already hard-navs to
//                         /app/login. App.tsx renders a neutral loading state and adds NO second
//                         competing redirect — exactly one bounce (T-09-11, SPA-04).
//
// T-09-10 (EoP): the shell never renders before this guard resolves 200; and every data call is
// independently auth-gated server-side (require_user → 401), so there is no client-trusted auth.

import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/shell/AppShell";
import { api } from "@/lib/http";

function App() {
  // The boot guard. retry:false (queryClient default) means a 401 surfaces immediately to the
  // global onAuthError, which performs the single redirect to /app/login.
  const { isSuccess, isError } = useQuery({
    queryKey: ["auth-me"],
    queryFn: () => api("/api/v2/auth/me"),
  });

  if (isSuccess) {
    return <AppShell />;
  }

  // Pending OR error (401 → global handler is mid-redirect). Render a neutral, brand-correct
  // loading state; do NOT add a competing redirect here (single bounce).
  return (
    <div className="flex min-h-svh items-center justify-center bg-background text-muted-foreground">
      <span className="text-sm" aria-live="polite">
        {isError ? "Redirecting…" : "Loading…"}
      </span>
    </div>
  );
}

export default App;
