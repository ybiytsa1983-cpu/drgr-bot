#!/usr/bin/env bash
# vm.sh — Launch Code VM (Monaco Editor + Flask) from the terminal.
# Usage: ./vm.sh [port]
#
# Examples:
#   ./vm.sh          # starts on default port 5000
#   ./vm.sh 8080     # starts on port 8080
#
# First-time setup: run ./install.sh once before using this script.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VM_PORT="${1:-${VM_PORT:-5000}}"
VENV_DIR="$SCRIPT_DIR/.venv"

# ── Pick Python: prefer venv, then system ─────────────────────────────────────
if [ -f "$VENV_DIR/bin/python" ]; then
    PYTHON="$VENV_DIR/bin/python"
    PIP="$VENV_DIR/bin/pip"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
    PIP="pip3"
elif command -v python &>/dev/null; then
    PYTHON="python"
    PIP="pip"
else
    echo "[Code VM] ERROR: Python not found."
    echo "  Run ./install.sh first, or install Python from https://python.org"
    exit 1
fi

# ── Install Flask / requests if missing ───────────────────────────────────────
if ! "$PYTHON" -c "import flask" 2>/dev/null; then
    echo "[Code VM] Installing dependencies (first run)..."
    "$PIP" install flask requests --quiet || {
        echo "[Code VM] ERROR: Failed to install dependencies."
        echo "  Run ./install.sh first, or: $PIP install flask requests"
        exit 1
    }
fi

# ── Start server ──────────────────────────────────────────────────────────────
echo "[Code VM] Starting server on port $VM_PORT ..."
VM_PORT=$VM_PORT "$PYTHON" vm/server.py &
SERVER_PID=$!

# ── Find local IP for network access ─────────────────────────────────────────
LOCAL_IP=$("$PYTHON" -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
    s.close()
except Exception:
    print('YOUR_IP')
" 2>/dev/null || echo "YOUR_IP")

# ── Wait until server responds on /health (up to 20 s) ───────────────────────
echo "[Code VM] Waiting for server to be ready..."
SERVER_READY=0
for i in $(seq 1 20); do
    sleep 1
    if "$PYTHON" -c "
import urllib.request, sys
try:
    r = urllib.request.urlopen('http://127.0.0.1:$VM_PORT/health', timeout=2)
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        SERVER_READY=1
        break
    fi
done

if [ "$SERVER_READY" -eq 0 ]; then
    echo "[Code VM] WARNING: server did not respond on /health within 20 s — check server.log"
fi

# ── Verify network accessibility ──────────────────────────────────────────────
if [ "$LOCAL_IP" != "YOUR_IP" ]; then
    NET_OK=0
    if "$PYTHON" -c "
import urllib.request, sys
try:
    r = urllib.request.urlopen('http://$LOCAL_IP:$VM_PORT/health', timeout=3)
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        NET_OK=1
        echo "[Code VM] ✓ Network check OK: http://$LOCAL_IP:$VM_PORT/health"
    else
        echo "[Code VM] ⚠ Network check FAILED: http://$LOCAL_IP:$VM_PORT/health"
        echo "           The server is running locally. Check your firewall if remote"
        echo "           devices cannot connect."
    fi
fi

# ── Open browser ──────────────────────────────────────────────────────────────
echo "[Code VM] Opening browser..."
if command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:$VM_PORT" 2>/dev/null &
elif command -v open &>/dev/null; then
    open "http://localhost:$VM_PORT"
fi

echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║  ⚡ Code VM is running!                          ║"
echo "  ╠══════════════════════════════════════════════════╣"
echo "  ║  Localhost  →  http://localhost:$VM_PORT/             ║"
echo "  ╠══════════════════════════════════════════════════╣"
echo "  ║  Ollama AI: run 'ollama serve' separately        ║"
echo "  ║  Press Ctrl+C to stop the VM                     ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo ""
echo "  Network access (open on any LAN device):"
echo "    Editor    → http://$LOCAL_IP:$VM_PORT/"
echo "    Navigator → http://$LOCAL_IP:$VM_PORT/navigator/"
echo "    Health    → http://$LOCAL_IP:$VM_PORT/health"
echo ""

# ── Wait for server process ───────────────────────────────────────────────────
wait "$SERVER_PID"

