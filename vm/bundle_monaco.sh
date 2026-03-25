#!/usr/bin/env bash
# bundle_monaco.sh - Downloads Monaco Editor core files for offline use.
# Linux / macOS equivalent of bundle_monaco.ps1
# Called automatically by install.sh during first-time setup.
# Result: vm/static/vendor/monaco/vs/  (~2.5 MB, no CDN needed at runtime)
#
# These 5 files are sufficient for Python/JavaScript editing:
#   loader.js             - AMD module loader
#   editor/editor.main.*  - core editor bundle (all basic-language tokenizers)
#   base/worker/workerMain.js - web worker host

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VERSION="0.44.0"
BASE="https://cdn.jsdelivr.net/npm/monaco-editor@${VERSION}/min/vs"
DEST="${SCRIPT_DIR}/static/vendor/monaco/vs"

# Skip if already bundled
if [ -f "${DEST}/loader.js" ]; then
    echo "  [OK] Monaco already bundled at: ${DEST}"
    exit 0
fi

echo "  [--] Downloading Monaco Editor core files (~2.5 MB)..."

# Create directory structure
mkdir -p "${DEST}/editor"
mkdir -p "${DEST}/base/worker"

FILES=(
    "loader.js"
    "editor/editor.main.js"
    "editor/editor.main.nls.js"
    "editor/editor.main.css"
    "base/worker/workerMain.js"
)

OK=0
TOTAL=${#FILES[@]}

for F in "${FILES[@]}"; do
    URL="${BASE}/${F}"
    OUT="${DEST}/${F}"
    ERR_TMP="$(mktemp)"
    if curl -fsSL --max-time 30 -o "${OUT}" "${URL}" 2>"${ERR_TMP}"; then
        OK=$((OK + 1))
    else
        echo "  [!] Failed to download: ${F} — $(cat "${ERR_TMP}" | head -1)"
    fi
    rm -f "${ERR_TMP}"
done

if [ "${OK}" -eq "${TOTAL}" ]; then
    echo "  [OK] Monaco bundled (${OK} files) — editor will work without internet"
    exit 0
else
    echo "  [!] Monaco bundle incomplete (${OK}/${TOTAL} files) — CDN fallback will be used"
    exit 1
fi
