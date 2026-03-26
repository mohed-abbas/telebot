#!/bin/bash
set -e

echo "=========================================="
echo "  MT5 Bridge Container Starting"
echo "  RPyC Port: ${RPYC_PORT:-18812}"
echo "  VNC Enabled: ${ENABLE_VNC:-false}"
echo "=========================================="

# Check if MT5 is installed
MT5_PATH="/root/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ ! -f "$MT5_PATH" ]; then
    echo ""
    echo "  MT5 NOT INSTALLED — First-time setup required!"
    echo ""
    echo "  1. Connect via browser: http://<VPS_IP>:6080/vnc.html"
    echo "  2. In the virtual desktop, open a terminal or file manager"
    echo "  3. Run: wine /opt/mt5setup.exe"
    echo "  4. Complete the MT5 installation wizard"
    echo "  5. Log into your broker account"
    echo "  6. Enable 'Auto Trading' and 'Allow DLL imports' in Tools > Options"
    echo "  7. Close MT5 — supervisord will restart it automatically"
    echo ""
    # Force VNC on for setup regardless of env var
    export ENABLE_VNC=true
fi

# Start supervisord (manages Xvfb, VNC, MT5, RPyC)
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
