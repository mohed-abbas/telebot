FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ENV WINEPREFIX=/root/.wine
ENV WINEARCH=win64
# Skip wine-mono and wine-gecko (MT5 doesn't need .NET or IE)
ENV WINEDLLOVERRIDES="mscoree=d;mshtml=d"

# ── System dependencies ──────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common wget gnupg2 ca-certificates \
    xvfb supervisor procps \
    cabextract xz-utils \
    x11vnc novnc python3-websockify \
    && rm -rf /var/lib/apt/lists/*

# ── Wine 6.0 (Ubuntu native — no "debugger detected" issue) ─────────
# Wine 11.x from WineHQ triggers MT5's anti-debugger check.
# Ubuntu's built-in Wine 6.0.3 predates this issue.
RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y wine wine64 \
    && rm -rf /var/lib/apt/lists/*

# ── Download installers (actual install happens at first container start) ─
RUN wget -O /opt/mt5setup.exe \
       "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" \
    && wget -O /opt/python-embed.zip \
       "https://www.python.org/ftp/python/3.9.13/python-3.9.13-embed-amd64.zip" \
    && wget -O /opt/get-pip.py \
       "https://bootstrap.pypa.io/get-pip.py" \
    && apt-get update && apt-get install -y --no-install-recommends unzip \
    && rm -rf /var/lib/apt/lists/*

# ── Scripts and config ────────────────────────────────────────────────
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY scripts/ /scripts/
RUN chmod +x /scripts/*.sh

# ── Runtime config ────────────────────────────────────────────────────
ENV RPYC_PORT=18812
ENV ENABLE_VNC=true

EXPOSE 18812 6080

VOLUME ["/root/.wine"]

ENTRYPOINT ["/scripts/entrypoint.sh"]
