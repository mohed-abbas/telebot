#!/bin/bash
set -e

echo "=========================================="
echo "  MT5 Bridge Container Starting"
echo "  RPyC Port: ${RPYC_PORT:-18812}"
echo "  VNC Enabled: ${ENABLE_VNC:-false}"
echo "=========================================="

# ── Start Xvfb (needed for Wine) ─────────────────────────────────────
echo "[1/4] Starting virtual display..."
Xvfb :99 -screen 0 1024x768x16 &>/dev/null &
sleep 3

# ── Initialize Wine prefix on first run ──────────────────────────────
if [ ! -f "/root/.wine/.initialized" ]; then
    echo ""
    echo "============================================"
    echo "  FIRST RUN — Initializing Wine environment"
    echo "  This takes 2-5 minutes, please wait..."
    echo "============================================"
    echo ""

    echo "[2/4] Initializing Wine prefix..."
    WINEDEBUG=-all wineboot --init 2>&1 || {
        echo "WARNING: wineboot returned non-zero, attempting fallback..."
        WINEDEBUG=-all WINEARCH=win32 wineboot --init 2>&1 || true
    }
    wineserver --wait 2>/dev/null || true
    echo "  Wine prefix ready."

    echo "[3/4] Installing Windows Python 3.9..."
    WINEDEBUG=-all wine /opt/python-installer.exe \
        /quiet TargetDir=C:\\Python39 PrependPath=1 2>&1 || {
        echo "ERROR: Python installation failed!"
        echo "Connect via noVNC and install manually:"
        echo "  wine /opt/python-installer.exe"
    }
    wineserver --wait 2>/dev/null || true
    echo "  Python installed."

    # Verify Python is accessible
    if wine C:\\Python39\\python.exe --version 2>/dev/null; then
        echo "[4/4] Installing MT5 Python packages..."
        WINEDEBUG=-all wine C:\\Python39\\python.exe -m pip install --upgrade pip 2>&1
        WINEDEBUG=-all wine C:\\Python39\\python.exe -m pip install MetaTrader5 mt5linux 2>&1
        wineserver --wait 2>/dev/null || true
        echo "  MT5 packages installed."
    else
        echo "WARNING: Python not found at C:\\Python39\\python.exe"
        echo "Connect via noVNC to install manually."
    fi

    touch /root/.wine/.initialized
    echo ""
    echo "============================================"
    echo "  Wine initialization complete!"
    echo "============================================"
else
    echo "Wine prefix already initialized, skipping setup."
fi

# ── Check if MT5 is installed ────────────────────────────────────────
MT5_PATH="/root/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ ! -f "$MT5_PATH" ]; then
    echo ""
    echo "============================================"
    echo "  MT5 NOT INSTALLED — Setup required!"
    echo ""
    echo "  1. Open browser: http://<VPS_IP>:6080/vnc.html"
    echo "     (or port 6081 for the second account)"
    echo "  2. Double-click desktop or open file manager"
    echo "  3. Run: wine /opt/mt5setup.exe"
    echo "  4. Complete the MT5 installation wizard"
    echo "  5. Log into your broker account"
    echo "  6. Tools > Options > Expert Advisors:"
    echo "     - Enable 'Allow algorithmic trading'"
    echo "     - Enable 'Allow DLL imports'"
    echo "  7. Close MT5 — supervisord will restart it"
    echo "============================================"
    echo ""
    # Force VNC on for setup
    export ENABLE_VNC=true
fi

# ── Stop the build-time Xvfb (supervisord will manage it) ────────────
kill $(cat /tmp/.X99-lock 2>/dev/null) 2>/dev/null || true
sleep 1

# ── Start supervisord ────────────────────────────────────────────────
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
