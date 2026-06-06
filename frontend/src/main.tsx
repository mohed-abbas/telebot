// frontend/src/main.tsx — the SPA provider root (D-07).
//
// Wires the two top-level providers Plan 01 left as a placeholder:
//   <QueryClientProvider client={queryClient}>  → TanStack Query (server state) for the whole tree
//     <RouterProvider router={router}/>          → the /app/* declarative router (basename "/app")
// plus the shadcn sonner <Toaster/> mounted once at the root for later toast use (Phase 11).
//
// queryClient (Plan 03) carries the single global onAuthError (SPA-04) and the polling defaults.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";

import "./index.css";
import { Toaster } from "@/components/ui/sonner";
import { queryClient } from "@/lib/queryClient";
import { router } from "@/routes/router";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>
  </StrictMode>,
);
