#!/usr/bin/env bash
# vm.sh — Launch Code VM (Monaco Editor + Flask) from the terminal.
# Usage: ./vm.sh [port]
#
# Examples:
#   ./vm.sh          # starts on default port 5000
#   ./vm.sh 8080     # starts on port 8080

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VM_PORT="${1:-${VM_PORT:-5000}}"

# ── Check Python ───────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[Code VM] ERROR: python3 not found. Please install Python 3.8+."
    exit 1
fi

# ── Install Flask / requests if missing ───────────────────────────────────────
if ! python3 -c "import flask" 2>/dev/null; then
    echo "[Code VM] Installing dependencies (first run)..."
    pip3 install flask requests --quiet || {
        echo "[Code VM] ERROR: Failed to install dependencies."
        echo "Please run manually: pip3 install flask requests"
        exit 1
    }
fi

# ── Start server ──────────────────────────────────────────────────────────────
echo "[Code VM] Starting server on port $VM_PORT..."
VM_PORT=$VM_PORT python3 vm/server.py &
SERVER_PID=$!

# ── Wait until server responds (up to 15 s) ───────────────────────────────────
echo "[Code VM] Waiting for server to be ready..."
for i in $(seq 1 15); do
    sleep 1
    if python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:$VM_PORT/')" 2>/dev/null; then
        break
    fi
done

# ── Open browser ──────────────────────────────────────────────────────────────
echo "[Code VM] Opening http://localhost:$VM_PORT ..."
if command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:$VM_PORT" 2>/dev/null &
elif command -v open &>/dev/null; then
    open "http://localhost:$VM_PORT"
fi

echo ""
echo "  Code VM is running at http://localhost:$VM_PORT"
echo "  Ollama AI: make sure 'ollama serve' is running for AI assistance."
echo "  Press Ctrl+C to stop."
echo ""

# ── Wait for server process ───────────────────────────────────────────────────
wait "$SERVER_PID"
