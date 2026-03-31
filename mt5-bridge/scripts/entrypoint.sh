#!/bin/bash
set -e

# ── Parse MT5_ACCOUNTS ────────────────────────────────────────────────
# Format: "name:port,name:port,..." (default: "default:18812")
IFS=',' read -ra ACCOUNTS <<< "${MT5_ACCOUNTS:-default:18812}"

echo "=========================================="
echo "  MT5 Bridge Container Starting"
echo "  Accounts:"
for account in "${ACCOUNTS[@]}"; do
    IFS=':' read -r name port <<< "$account"
    echo "    - ${name} (RPyC port: ${port})"
done
echo "  VNC Enabled: ${ENABLE_VNC:-false}"
echo "=========================================="

# ── Start Xvfb for Wine init ──────────────────────────────────────────
echo "[init] Starting virtual display for Wine initialization..."
Xvfb :99 -screen 0 1024x768x16 &>/dev/null &
sleep 3

# ── Initialize Wine prefix per account ────────────────────────────────
init_wine_prefix() {
    local name="$1"
    export WINEPREFIX="/root/.wine-${name}"

    if [ -f "${WINEPREFIX}/.initialized" ]; then
        echo "[${name}] Wine prefix already initialized, skipping."
        return 0
    fi

    echo ""
    echo "============================================"
    echo "  [${name}] FIRST RUN — Initializing Wine"
    echo "  This takes 2-5 minutes, please wait..."
    echo "============================================"
    echo ""

    echo "[${name}] Initializing Wine prefix..."
    WINEDEBUG=-all wineboot --init 2>&1 || {
        echo "WARNING: wineboot returned non-zero, attempting fallback..."
        WINEDEBUG=-all WINEARCH=win32 wineboot --init 2>&1 || true
    }
    wineserver --wait 2>/dev/null || true
    echo "  Wine prefix ready."

    echo "[${name}] Installing Python 3.9 (embeddable)..."
    PYDIR="${WINEPREFIX}/drive_c/Python39"
    mkdir -p "$PYDIR"
    unzip -o /opt/python-embed.zip -d "$PYDIR" > /dev/null
    # Enable site-packages (needed for pip)
    sed -i 's/^#import site/import site/' "$PYDIR/python39._pth"
    echo "  Python extracted."

    echo "[${name}] Installing pip and MT5 packages..."
    cp /opt/get-pip.py "$PYDIR/get-pip.py"
    WINEDEBUG=-all wine "$PYDIR/python.exe" "$PYDIR/get-pip.py" --no-warn-script-location 2>&1
    wineserver --wait 2>/dev/null || true

    WINEDEBUG=-all wine "$PYDIR/python.exe" -m pip install MetaTrader5 mt5linux --no-warn-script-location 2>&1
    wineserver --wait 2>/dev/null || true

    # Verify Python works (don't import MetaTrader5 — it hangs without a running terminal)
    if wine "$PYDIR/python.exe" -c "import rpyc; print('RPyC', rpyc.__version__)" 2>/dev/null; then
        echo "  MT5 packages installed successfully."
    else
        echo "WARNING: Package verification failed. Check logs."
    fi

    rm -f "$PYDIR/get-pip.py"
    touch "${WINEPREFIX}/.initialized"
    echo ""
    echo "============================================"
    echo "  [${name}] Wine initialization complete!"
    echo "============================================"
}

# ── Run init for each account ─────────────────────────────────────────
for account in "${ACCOUNTS[@]}"; do
    IFS=':' read -r name port <<< "$account"
    init_wine_prefix "$name"
done

# ── Check MT5 installation per account ────────────────────────────────
ANY_MISSING=false
for account in "${ACCOUNTS[@]}"; do
    IFS=':' read -r name port <<< "$account"
    MT5_PATH="/root/.wine-${name}/drive_c/Program Files/MetaTrader 5/terminal64.exe"
    if [ ! -f "$MT5_PATH" ]; then
        ANY_MISSING=true
        echo ""
        echo "============================================"
        echo "  [${name}] MT5 NOT INSTALLED — Setup required!"
        echo ""
        echo "  1. Open browser: http://<VPS_IP>:6080/vnc.html"
        echo "  2. Run on VPS:"
        echo "     docker exec -d mt5-bridge bash -c \\"
        echo "       'DISPLAY=:99 WINEPREFIX=/root/.wine-${name} WINEDEBUG=-all wine /opt/mt5setup.exe'"
        echo "  3. Complete the MT5 installation wizard"
        echo "  4. Log into your broker account"
        echo "  5. Tools > Options > Expert Advisors:"
        echo "     - Enable 'Allow algorithmic trading'"
        echo "     - Enable 'Allow DLL imports'"
        echo "  6. Close MT5 — supervisord will restart it"
        echo "============================================"
        echo ""
    fi
done

if [ "$ANY_MISSING" = true ]; then
    export ENABLE_VNC=true
fi

# ── Generate supervisord.conf dynamically ─────────────────────────────
cat > /etc/supervisor/conf.d/supervisord.conf <<EOF
[supervisord]
nodaemon=true
logfile=/var/log/supervisord.log
pidfile=/var/run/supervisord.pid

[unix_http_server]
file=/var/run/supervisor.sock

[supervisorctl]
serverurl=unix:///var/run/supervisor.sock

# ── Virtual framebuffer (always on) ──────────────────────────────────
[program:xvfb]
command=/usr/bin/Xvfb :99 -screen 0 1024x768x16
autorestart=true
priority=10
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

# ── VNC server (setup mode or when ENABLE_VNC=true) ─────────────────
[program:x11vnc]
command=/usr/bin/x11vnc -display :99 -forever -nopw -listen 0.0.0.0 -rfbport 5900
autorestart=true
priority=20
autostart=${ENABLE_VNC}
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

# ── noVNC web proxy (setup mode or when ENABLE_VNC=true) ─────────────
[program:novnc]
command=websockify --web /usr/share/novnc 6080 localhost:5900
autorestart=true
priority=25
autostart=${ENABLE_VNC}
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
EOF

# ── Append per-account programs ───────────────────────────────────────
OFFSET=0
for account in "${ACCOUNTS[@]}"; do
    IFS=':' read -r name port <<< "$account"
    MT5_PRIORITY=$((30 + OFFSET))
    RPYC_PRIORITY=$((40 + OFFSET))

    cat >> /etc/supervisor/conf.d/supervisord.conf <<EOF

# ── MT5 terminal: ${name} ────────────────────────────────────────────
[program:mt5-${name}]
command=wine "/root/.wine-${name}/drive_c/Program Files/MetaTrader 5/terminal64.exe" /portable
autorestart=true
priority=${MT5_PRIORITY}
startsecs=10
startretries=5
environment=DISPLAY=":99",WINEPREFIX="/root/.wine-${name}"
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

# ── RPyC bridge: ${name} (port ${port}) ──────────────────────────────
[program:rpyc-${name}]
command=wine /root/.wine-${name}/drive_c/Python39/python.exe -m mt5linux --host 0.0.0.0 -p ${port}
autorestart=true
priority=${RPYC_PRIORITY}
startsecs=15
startretries=10
environment=DISPLAY=":99",WINEPREFIX="/root/.wine-${name}"
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
EOF

    OFFSET=$((OFFSET + 10))
done

# ── Stop the init-time Xvfb (supervisord will manage it) ─────────────
kill $(cat /tmp/.X99-lock 2>/dev/null) 2>/dev/null || true
sleep 1

# ── Start supervisord ────────────────────────────────────────────────
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
