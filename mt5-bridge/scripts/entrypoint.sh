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

    echo "[3/4] Installing Python 3.9 (embeddable)..."
    PYDIR="/root/.wine/drive_c/Python39"
    mkdir -p "$PYDIR"
    unzip -o /opt/python-embed.zip -d "$PYDIR" > /dev/null
    # Enable site-packages (needed for pip)
    sed -i 's/^#import site/import site/' "$PYDIR/python39._pth"
    echo "  Python extracted."

    echo "[4/4] Installing pip and MT5 packages..."
    # Copy get-pip.py into the Python directory so Wine can find it
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
    echo "  2. Run on VPS:"
    echo "     docker exec -d mt5-vantage bash -c \\"
    echo "       'DISPLAY=:99 wine /opt/mt5setup.exe'"
    echo "  3. Complete the MT5 installation wizard"
    echo "  4. Log into your broker account"
    echo "  5. Tools > Options > Expert Advisors:"
    echo "     - Enable 'Allow algorithmic trading'"
    echo "     - Enable 'Allow DLL imports'"
    echo "  6. Close MT5 — supervisord will restart it"
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
