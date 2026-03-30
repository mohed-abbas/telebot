FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ENV WINEARCH=win64
# Skip wine-mono and wine-gecko (MT5 doesn't need .NET or IE)
ENV WINEDLLOVERRIDES="mscoree=d;mshtml=d"

# ── All dependencies in a single layer ───────────────────────────────
RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       software-properties-common wget gnupg2 ca-certificates \
       xvfb supervisor procps \
       cabextract xz-utils unzip \
       x11vnc novnc python3-websockify \
       wine wine64 \
    && wget -O /opt/mt5setup.exe \
       "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" \
    && wget -O /opt/python-embed.zip \
       "https://www.python.org/ftp/python/3.9.13/python-3.9.13-embed-amd64.zip" \
    && wget -O /opt/get-pip.py \
       "https://bootstrap.pypa.io/get-pip.py" \
    && apt-get purge -y --auto-remove software-properties-common gnupg2 \
    && rm -rf /var/lib/apt/lists/*

# ── Scripts ──────────────────────────────────────────────────────────
COPY scripts/ /scripts/
RUN chmod +x /scripts/*.sh

# ── Runtime config ───────────────────────────────────────────────────
ENV ENABLE_VNC=false

EXPOSE 6080

ENTRYPOINT ["/scripts/entrypoint.sh"]
