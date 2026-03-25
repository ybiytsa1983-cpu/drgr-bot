#!/usr/bin/env bash
# start.sh — ONE command to launch Code VM on Linux / macOS.
#
#   First launch:  installs everything, then opens the editor.
#   Later launches: opens the editor immediately.
#
# Usage:
#   chmod +x start.sh   (once, to make executable)
#   ./start.sh

set -e
cd "$(dirname "${BASH_SOURCE[0]}")"

# ── First-time setup if .venv is missing ──────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo ""
    echo "  ⚡ Code VM — первый запуск, устанавливаем зависимости..."
    echo "  Подождите ~1 минуту."
    echo ""

    # Find Python 3.8+
    PYTHON=""
    for cmd in python3 python3.12 python3.11 python3.10 python3.9 python3.8 python; do
        if command -v "$cmd" &>/dev/null; then
            maj=$("$cmd" -c "import sys;print(sys.version_info.major)" 2>/dev/null || echo 0)
            mn=$("$cmd"  -c "import sys;print(sys.version_info.minor)" 2>/dev/null || echo 0)
            if [ "$maj" -ge 3 ] && [ "$mn" -ge 8 ]; then
                PYTHON="$cmd"; break
            fi
        fi
    done

    if [ -z "$PYTHON" ]; then
        echo "  [ОШИБКА] Python 3.8+ не найден."
        echo "  macOS:  brew install python"
        echo "  Ubuntu: sudo apt install python3 python3-venv"
        exit 1
    fi

    "$PYTHON" -m venv .venv
    .venv/bin/pip install flask requests --quiet
    if [ -f requirements.txt ]; then
        .venv/bin/pip install -r requirements.txt --quiet 2>/dev/null || true
    fi
    echo "  [OK] Установка завершена."
    echo ""
fi

chmod +x vm.sh 2>/dev/null || true
exec ./vm.sh
