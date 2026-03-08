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

# ── Wait until server responds (up to 15 s) ───────────────────────────────────
echo "[Code VM] Waiting for server to be ready..."
for i in $(seq 1 15); do
    sleep 1
    if "$PYTHON" -c "import urllib.request; urllib.request.urlopen('http://localhost:$VM_PORT/')" 2>/dev/null; then
        break
    fi
done

# ── Open browser ──────────────────────────────────────────────────────────────
echo "[Code VM] Opening browser..."
if command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:$VM_PORT" 2>/dev/null &
elif command -v open &>/dev/null; then
    open "http://localhost:$VM_PORT"
fi

# ── Find local IP for Android access ─────────────────────────────────────────
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

echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║  ⚡ Code VM is running!                          ║"
echo "  ╠══════════════════════════════════════════════════╣"
echo "  ║  Code VM    →  http://localhost:$VM_PORT/             ║"
echo "  ║  Navigator  →  http://localhost:$VM_PORT/navigator/   ║"
echo "  ╠══════════════════════════════════════════════════╣"
echo "  ║  Android    →  http://$LOCAL_IP:$VM_PORT/navigator/   ║"
echo "  ║  (open this URL in Chrome on your Android phone) ║"
echo "  ╠══════════════════════════════════════════════════╣"
echo "  ║  Ollama AI: run 'ollama serve' separately        ║"
echo "  ║  Press Ctrl+C to stop the VM                     ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo ""

# ── Wait for server process ───────────────────────────────────────────────────
wait "$SERVER_PID"

