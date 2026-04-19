# ── Stage 1: CSS build (Tailwind v3.4.19 standalone CLI) ────────────
FROM debian:bookworm-slim AS css-build
ARG TAILWIND_VERSION=v3.4.19
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates python3 \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-x64" \
        -o /usr/local/bin/tailwindcss \
    && chmod +x /usr/local/bin/tailwindcss

WORKDIR /build
# Copy only what the content glob needs — layer cache invalidates on template/py changes
COPY tailwind.config.js ./
COPY static/css/input.css static/css/_compat.css ./static/css/
COPY static/vendor/ ./static/vendor/
COPY templates/ ./templates/
COPY *.py ./
COPY scripts/build_css.sh ./scripts/
RUN bash scripts/build_css.sh

# ── Stage 2: runtime ────────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py *.json ./
COPY templates/ ./templates/
COPY static/ ./static/
COPY scripts/ ./scripts/

# Overlay the hashed CSS + manifest from the build stage
COPY --from=css-build /build/static/css/app.*.css ./static/css/
COPY --from=css-build /build/static/css/manifest.json ./static/css/

RUN mkdir -p /app/data
EXPOSE 8080
CMD ["python", "-u", "bot.py"]
