import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

// https://vite.dev/config/
export default defineConfig({
  // D-01 / Pitfall 3: SPA is served under the /app/ subpath behind nginx, mounted by
  // dashboard.py at app.mount("/app"). base bakes /app/assets/* into the built bundle so
  // hashed assets resolve under the subpath. At base "/" the built bundle 404s its assets.
  base: "/app/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      // D-12 / Pitfall 4: forward /api to the dev container (docker-compose.dev.yml
      // DASHBOARD_HOST_PORT default 8090; 8080 collides with devdock-caddy). changeOrigin:false
      // preserves Host so the telebot_session cookie domain stays the Vite origin (same-origin
      // in dev — the httpOnly session cookie is attached on subsequent /api calls, no redirect loop).
      // Only /api is proxied: the SPA login is POST /api/v2/auth/login, NOT a legacy top-level /login.
      "/api": { target: "http://localhost:8090", changeOrigin: false },
    },
  },
});
