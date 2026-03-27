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

# ── Wine (stable from WineHQ) ────────────────────────────────────────
RUN dpkg --add-architecture i386 \
    && mkdir -pm755 /etc/apt/keyrings \
    && wget -O /etc/apt/keyrings/winehq-archive.key \
       https://dl.winehq.org/wine-builds/winehq.key \
    && wget -NP /etc/apt/sources.list.d/ \
       https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources \
    && apt-get update \
    && apt-get install -y --install-recommends winehq-stable \
    && rm -rf /var/lib/apt/lists/*

# ── Download installers (actual install happens at first container start) ─
RUN wget -O /opt/mt5setup.exe \
       "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" \
    && wget -O /opt/python-installer.exe \
       "https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe"

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
