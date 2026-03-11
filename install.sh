#!/usr/bin/env bash
# install.sh — First-time setup for Code VM on Linux / macOS.
#
# Usage:
#   chmod +x install.sh
#   ./install.sh
#
# What it does:
#   1. Checks for Python 3.8+
#   2. Creates a virtual environment (.venv) in the repo root
#   3. Installs Python dependencies into the venv
#   4. Prints Ollama installation instructions
#   5. Optionally pulls the recommended AI model

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
REQUIRED_PYTHON_MINOR=8

# ── Colours ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✓  $*${RESET}"; }
info() { echo -e "${CYAN}  →  $*${RESET}"; }
warn() { echo -e "${YELLOW}  ⚠  $*${RESET}"; }
err()  { echo -e "${RED}  ✗  $*${RESET}" >&2; }

echo ""
echo -e "${BOLD}⚡ Code VM — First-time setup${RESET}"
echo "────────────────────────────────────────"

# ── 1. Find Python ─────────────────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python3.12 python3.11 python3.10 python3.9 python3.8 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "0")
        maj=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null || echo "0")
        if [ "$maj" -ge 3 ] && [ "$ver" -ge "$REQUIRED_PYTHON_MINOR" ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    err "Python 3.${REQUIRED_PYTHON_MINOR}+ not found."
    echo ""
    echo "  Install Python:"
    echo "    macOS:  brew install python"
    echo "    Ubuntu: sudo apt install python3 python3-pip python3-venv"
    echo "    Other:  https://www.python.org/downloads/"
    exit 1
fi

PY_VERSION=$("$PYTHON" --version 2>&1)
ok "Python found: $PY_VERSION ($PYTHON)"

# ── 2. Create virtual environment ──────────────────────────────────────────────
if [ -d "$VENV_DIR" ]; then
    ok "Virtual environment already exists (.venv)"
else
    info "Creating virtual environment at .venv ..."
    "$PYTHON" -m venv "$VENV_DIR"
    ok "Virtual environment created"
fi

# ── 3. Activate venv ───────────────────────────────────────────────────────────
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# ── 4. Upgrade pip silently ────────────────────────────────────────────────────
info "Upgrading pip..."
"$VENV_PIP" install --upgrade pip --quiet
ok "pip up to date"

# ── 5. Install dependencies ────────────────────────────────────────────────────
info "Installing Python dependencies..."
"$VENV_PIP" install flask requests --quiet
ok "Flask + requests installed"

# Install the full requirements.txt if it exists
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    info "Installing requirements.txt..."
    "$VENV_PIP" install -r "$SCRIPT_DIR/requirements.txt" --quiet 2>/dev/null || \
        warn "Some optional packages in requirements.txt failed (Telegram bot deps) — VM will still work"
fi

# ── 5b. Install Playwright browsers ───────────────────────────────────────────
if "$VENV_PYTHON" -c "import playwright" 2>/dev/null; then
    info "Installing Playwright browsers (Chromium)..."
    "$VENV_PYTHON" -m playwright install chromium --quiet 2>/dev/null && \
        ok "Playwright Chromium browser installed" || \
        warn "Playwright browser install failed — screenshots will not work"
fi

# ── 5c. Create .env file from example if not present ─────────────────────────
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
        warn ".env created from .env.example — please edit it and set BOT_TOKEN"
    fi
fi

# ── 6. Make launchers executable ──────────────────────────────────────────────
chmod +x "$SCRIPT_DIR/vm.sh" 2>/dev/null || true
chmod +x "$SCRIPT_DIR/vm/bundle_monaco.sh" 2>/dev/null || true
ok "Launchers are executable"

# ── 6b. Bundle Monaco Editor for offline use ──────────────────────────────────
BUNDLE_SCRIPT="$SCRIPT_DIR/vm/bundle_monaco.sh"
if [ -f "$BUNDLE_SCRIPT" ]; then
    info "Downloading Monaco Editor (offline code editor)..."
    bash "$BUNDLE_SCRIPT" && ok "Monaco Editor downloaded — editor works without internet" || \
        warn "Could not download Monaco — CDN will be used as fallback."
else
    warn "vm/bundle_monaco.sh not found — CDN will be used as fallback."
fi

# ── 7. Ollama instructions ─────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}🤖 Ollama (AI features — optional)${RESET}"
echo "────────────────────────────────────────"

if command -v ollama &>/dev/null; then
    ok "Ollama already installed: $(ollama --version 2>/dev/null || echo 'version unknown')"
    echo ""
    info "Pull the recommended model (first time, ~5 GB):"
    echo ""
    echo "      ollama pull qwen3-vl:8b"
    echo "      ollama serve           # keep running in a separate terminal"
else
    warn "Ollama not found — AI code generation will not work until you install it."
    echo ""
    echo "  Install Ollama:"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "    brew install ollama"
    else
        echo "    curl -fsSL https://ollama.com/install.sh | sh"
    fi
    echo ""
    echo "  Then pull the model and keep it running:"
    echo "    ollama pull qwen3-vl:8b"
    echo "    ollama serve"
fi

# ── 8. Done ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}────────────────────────────────────────${RESET}"
echo -e "${GREEN}${BOLD}  ✓  Setup complete!${RESET}"
echo ""
echo "  Launch the VM:"
echo -e "    ${CYAN}./vm.sh${RESET}          (Linux / macOS)"
echo ""
echo "  Launch the Telegram bot:"
echo -e "    ${CYAN}source .venv/bin/activate && python bot.py${RESET}"
echo ""
echo "  Then open in browser:"
echo -e "    ${CYAN}http://localhost:5000/${RESET}            ⚡ Code VM"
echo -e "    ${CYAN}http://localhost:5000/navigator/${RESET}  🧭 Android Navigator"
echo ""
