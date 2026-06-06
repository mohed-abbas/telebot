# ── Stage 1: CSS build (Tailwind v4 standalone CLI) ─────────────────
# v4 (Basecoat v0.3.3 is Tailwind-v4-native — uses @custom-variant / @theme /
# has-data-[slot=...]). v4 CLI natively resolves CSS @import statements; v3's
# CLI silently dropped them (UAT Gap #1). Asset name tailwindcss-linux-x64 is
# identical across v3/v4 releases.
FROM debian:bookworm-slim AS css-build
# WR-06: keep this pinned to the SAME minor the SPA build resolves via
# @tailwindcss/vite (frontend/package.json: tailwindcss ^4.3.0 → 4.3.0). The HTMX
# stylesheet (this standalone CLI) and the SPA stylesheet (Vite plugin) both render
# the shared brand palette during the parallel-run window; a version skew (4.2.x vs
# 4.3.x) can drift @theme/@custom-variant semantics and make the two render the
# palette differently. Bump both together if the npm range moves.
ARG TAILWIND_VERSION=v4.3.0
# TARGETARCH is auto-populated by BuildKit (amd64 / arm64). v4's standalone CLI
# ships native binaries for both — pick the matching one, otherwise the
# linux-x64 binary trips Rosetta/qemu emulation on Apple Silicon dev machines
# ("rosetta error: failed to open elf at /lib64/ld-linux-x86-64.so.2"; exit 133).
# Release assets: tailwindcss-linux-x64 (amd64) + tailwindcss-linux-arm64 (arm64).
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates python3 \
    && rm -rf /var/lib/apt/lists/*
RUN case "${TARGETARCH}" in \
        amd64) TW_ASSET="tailwindcss-linux-x64" ;; \
        arm64) TW_ASSET="tailwindcss-linux-arm64" ;; \
        *)     echo "Unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/${TW_ASSET}" \
        -o /usr/local/bin/tailwindcss \
    && chmod +x /usr/local/bin/tailwindcss

WORKDIR /build
# Copy only what the content glob needs — layer cache invalidates on template/py changes
COPY tailwind.config.js ./
COPY static/css/input.css ./static/css/
COPY static/vendor/ ./static/vendor/
COPY templates/ ./templates/
COPY *.py ./
COPY scripts/build_css.sh ./scripts/
RUN bash scripts/build_css.sh

# ── Stage 2: SPA build (Vite/React, Phase 09 SPA-01 / D-03) ─────────
# Node lives ONLY in this build stage — the runtime image stays python:3.12-slim
# with no Node (minimize-deps). Coexists with css-build until the HTMX dashboard
# is decommissioned in Phase 12. Vite emits /spa/dist with base:/app/.
FROM node:22-slim AS spa-build
WORKDIR /spa
# Copy manifests first so `npm ci` layer caches on lockfile changes only.
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 3: runtime ────────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py *.json ./
COPY api/ ./api/
COPY templates/ ./templates/
COPY static/ ./static/
COPY scripts/ ./scripts/

# Overlay the hashed CSS + manifest from the build stage
COPY --from=css-build /build/static/css/app.*.css ./static/css/
COPY --from=css-build /build/static/css/manifest.json ./static/css/

# Overlay the built SPA bundle (served at /app by uvicorn StaticFiles — SPA-01)
COPY --from=spa-build /spa/dist/ ./static/app/

RUN mkdir -p /app/data
EXPOSE 8080
CMD ["python", "-u", "bot.py"]
