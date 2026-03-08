# bundle_monaco.ps1 - Downloads Monaco Editor core files for offline use.
# Called automatically by install.bat during first-time setup.
# Result: vm/static/vendor/monaco/vs/  (~2.5 MB, no CDN needed at runtime)
#
# These 5 files are sufficient for Python/JavaScript editing:
#   loader.js             - AMD module loader
#   editor/editor.main.*  - core editor bundle (includes all basic-language
#                           tokenizers for Python/JS/HTML/CSS/etc.)
#   base/worker/workerMain.js - web worker host (used by editor internals)

$ErrorActionPreference = 'Stop'

$version = '0.44.0'
$base    = "https://cdn.jsdelivr.net/npm/monaco-editor@$version/min/vs"
$dest    = Join-Path $PSScriptRoot "static\vendor\monaco\vs"

# Skip if already bundled
if (Test-Path (Join-Path $dest 'loader.js')) {
    Write-Host "  [OK] Monaco already bundled at: $dest"
    exit 0
}

Write-Host "  [--] Downloading Monaco Editor core files (~2.5 MB)..."

# Create directory structure
New-Item -ItemType Directory -Force -Path "$dest\editor" | Out-Null
New-Item -ItemType Directory -Force -Path "$dest\base\worker" | Out-Null

$files = @(
    'loader.js',
    'editor/editor.main.js',
    'editor/editor.main.nls.js',
    'editor/editor.main.css',
    'base/worker/workerMain.js'
)

$ok = 0
foreach ($f in $files) {
    $url = "$base/$f"
    $out = Join-Path $dest ($f -replace '/', '\')
    try {
        Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
        $ok++
    } catch {
        Write-Host "  [!] Failed to download: $f"
    }
}

if ($ok -eq $files.Count) {
    Write-Host "  [OK] Monaco bundled ($ok files) - editor will work without internet"
    exit 0
} else {
    Write-Host "  [!] Monaco bundle incomplete ($ok/$($files.Count) files) - CDN fallback will be used"
    exit 1
}
