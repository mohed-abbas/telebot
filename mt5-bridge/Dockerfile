FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ENV WINEPREFIX=/root/.wine
ENV WINEARCH=win64

# Skip wine-mono and wine-gecko downloads (MT5 doesn't need .NET or IE)
ENV WINEDLLOVERRIDES="mscoree=d;mshtml=d"

# ── System dependencies ──────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common wget gnupg2 ca-certificates \
    xvfb supervisor procps \
    cabextract xz-utils \
    x11vnc novnc python3-websockify \
    && rm -rf /var/lib/apt/lists/*

# ── Wine 10.0 (oldstable — Wine 11.x breaks MT5 in Docker) ──────────
RUN dpkg --add-architecture i386 \
    && mkdir -pm755 /etc/apt/keyrings \
    && wget -O /etc/apt/keyrings/winehq-archive.key \
       https://dl.winehq.org/wine-builds/winehq.key \
    && wget -NP /etc/apt/sources.list.d/ \
       https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources \
    && apt-get update \
    && apt-get install -y --install-recommends winehq-oldstable \
    && rm -rf /var/lib/apt/lists/*

# ── Initialize Wine prefix ───────────────────────────────────────────
# Start Xvfb manually (more reliable than xvfb-run in Docker builds)
RUN Xvfb :99 -screen 0 1024x768x16 &>/dev/null & \
    sleep 2 && \
    WINEDEBUG=-all wineboot --init && \
    wineserver --wait && \
    kill $(cat /tmp/.X99-lock 2>/dev/null) 2>/dev/null || true

# ── Windows Python 3.12 (inside Wine) ────────────────────────────────
RUN wget -O /tmp/python-installer.exe \
    "https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe" \
    && Xvfb :99 -screen 0 1024x768x16 &>/dev/null & \
    sleep 2 && \
    WINEDEBUG=-all wine /tmp/python-installer.exe \
       /quiet TargetDir=C:\\Python312 PrependPath=1 && \
    wineserver --wait && \
    rm /tmp/python-installer.exe && \
    kill $(cat /tmp/.X99-lock 2>/dev/null) 2>/dev/null || true

# ── MT5 Python packages (RPyC bridge) ────────────────────────────────
RUN Xvfb :99 -screen 0 1024x768x16 &>/dev/null & \
    sleep 2 && \
    WINEDEBUG=-all wine C:\\Python312\\python.exe -m pip install --upgrade pip && \
    WINEDEBUG=-all wine C:\\Python312\\python.exe -m pip install \
       MetaTrader5 mt5linux && \
    wineserver --wait && \
    kill $(cat /tmp/.X99-lock 2>/dev/null) 2>/dev/null || true

# ── MT5 installer (run interactively on first boot via noVNC) ─────────
RUN wget -O /opt/mt5setup.exe \
    "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"

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
