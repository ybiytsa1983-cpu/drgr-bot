<#
.SYNOPSIS
    First-time setup for Code VM on Windows (PowerShell).

.DESCRIPTION
    Run once after cloning the repository:
        .\install.ps1

    What it does:
      1. Checks for Python 3.8+
      2. Creates a virtual environment (.venv)
      3. Installs Python dependencies (Flask, requests)
      4. Prints Ollama installation instructions

.NOTES
    If you see "script cannot be loaded because running scripts is disabled",
    run this once to allow local scripts:
        Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
    Then re-run: .\install.ps1
#>

$ErrorActionPreference = "Stop"

$repoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoDir

$venvDir = Join-Path $repoDir ".venv"

# ── Helpers ───────────────────────────────────────────────────────────────────
function Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Info($msg) { Write-Host "  [--] $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Err($msg)  { Write-Host "  [ERROR] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "  =============================================" -ForegroundColor White
Write-Host "   Code VM — First-time setup (PowerShell)    " -ForegroundColor White
Write-Host "  =============================================" -ForegroundColor White
Write-Host ""

# ── 1. Find Python ────────────────────────────────────────────────────────────
$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 8) {
                $python = $cmd
                Ok "Python found: $ver"
                break
            }
        }
    } catch { }
}

if (-not $python) {
    Err "Python 3.8+ not found."
    Write-Host ""
    Write-Host "  Download Python from:" -ForegroundColor Yellow
    Write-Host "    https://www.python.org/downloads/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  IMPORTANT: During installation, check 'Add Python to PATH'" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Press Enter to exit"
    exit 1
}

# ── 2. Create virtual environment ─────────────────────────────────────────────
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvPip    = Join-Path $venvDir "Scripts\pip.exe"

if (Test-Path $venvPython) {
    Ok "Virtual environment already exists (.venv)"
} else {
    Info "Creating virtual environment (.venv)..."
    & $python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Err "Failed to create virtual environment."
        Read-Host "  Press Enter to exit"
        exit 1
    }
    Ok "Virtual environment created"
}

# ── 3. Upgrade pip ────────────────────────────────────────────────────────────
Info "Upgrading pip..."
& $venvPip install --upgrade pip --quiet 2>$null
Ok "pip up to date"

# ── 4. Install Flask + requests ───────────────────────────────────────────────
Info "Installing Flask + requests..."
& $venvPip install flask requests --quiet
if ($LASTEXITCODE -ne 0) {
    Err "Failed to install Flask/requests."
    Read-Host "  Press Enter to exit"
    exit 1
}
Ok "Flask + requests installed"

# ── 5. Install requirements.txt (optional extras) ─────────────────────────────
$reqFile = Join-Path $repoDir "requirements.txt"
if (Test-Path $reqFile) {
    Info "Installing requirements.txt (Telegram bot deps)..."
    & $venvPip install -r $reqFile --quiet 2>$null
    Ok "requirements.txt processed"
}

# ── 6. Ollama instructions ────────────────────────────────────────────────────
Write-Host ""
Write-Host "  =============================================" -ForegroundColor White
Write-Host "   Ollama (AI features — optional)            " -ForegroundColor White
Write-Host "  =============================================" -ForegroundColor White
Write-Host ""

$ollamaOk = $null
try { $ollamaOk = & ollama --version 2>&1 } catch { }

if ($ollamaOk) {
    Ok "Ollama already installed: $ollamaOk"
    Write-Host ""
    Write-Host "  Pull the recommended model (first time, ~5 GB):" -ForegroundColor Cyan
    Write-Host "    ollama pull qwen3-vl:8b" -ForegroundColor White
    Write-Host "    ollama serve           # run in a separate terminal" -ForegroundColor White
} else {
    Warn "Ollama not found — AI code generation will not work until you install it."
    Write-Host ""
    Write-Host "  Download and install from:" -ForegroundColor Yellow
    Write-Host "    https://ollama.com/download" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  After installing, run in a separate terminal:" -ForegroundColor Yellow
    Write-Host "    ollama pull qwen3-vl:8b" -ForegroundColor White
    Write-Host "    ollama serve" -ForegroundColor White
}

# ── 7. Done ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  =============================================" -ForegroundColor Green
Write-Host "   Setup complete!                            " -ForegroundColor Green
Write-Host "  =============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Launch the VM:" -ForegroundColor White
Write-Host "    .\vm.ps1        (PowerShell)" -ForegroundColor Cyan
Write-Host "    vm.bat          (cmd.exe / double-click)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Then open in browser:" -ForegroundColor White
Write-Host "    http://localhost:5000/            Code VM" -ForegroundColor Cyan
Write-Host "    http://localhost:5000/navigator/  Android Navigator" -ForegroundColor Cyan
Write-Host ""
