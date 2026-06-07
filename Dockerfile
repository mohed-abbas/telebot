# ── Stage 1: SPA build (Vite/React, Phase 09 SPA-01 / D-03) ─────────
# Node lives ONLY in this build stage — the runtime image stays python:3.12-slim
# with no Node (minimize-deps). The legacy Tailwind-CLI css-build stage was
# removed in Phase 12 (CUT-03) when the HTMX dashboard was decommissioned; SPA
# CSS now comes from @tailwindcss/vite inside this stage. Vite emits /spa/dist
# with base:/app/.
FROM node:22-slim AS spa-build
WORKDIR /spa
# Copy manifests first so `npm ci` layer caches on lockfile changes only.
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: runtime ────────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py *.json ./
COPY api/ ./api/
COPY static/ ./static/
COPY scripts/ ./scripts/

# Overlay the built SPA bundle (served at /app by uvicorn StaticFiles — SPA-01)
COPY --from=spa-build /spa/dist/ ./static/app/

RUN mkdir -p /app/data
EXPOSE 8080
CMD ["python", "-u", "bot.py"]
