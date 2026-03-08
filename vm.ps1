<#
.SYNOPSIS
    Launch Code VM (Monaco Editor + Flask) from PowerShell.

.DESCRIPTION
    Usage:
        .\vm.ps1           # starts on default port 5000
        .\vm.ps1 8080      # starts on port 8080

    First-time setup: run .\install.ps1 once before using this script.

    If you see "script cannot be loaded because running scripts is disabled",
    run this once:
        Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
    Then re-run: .\vm.ps1

.PARAMETER Port
    Port to run the VM on. Defaults to 5000 (or $env:VM_PORT if set).
#>

param(
    [int]$Port = $(if ($env:VM_PORT) { [int]$env:VM_PORT } else { 5000 })
)

$ErrorActionPreference = "Stop"

# $PSScriptRoot is empty when PS is invoked without -File (e.g. some shortcuts
# or "powershell vm.ps1" instead of "powershell -File vm.ps1").
# Fall back to $MyInvocation, then to the current working directory.
$repoDir = if ($PSScriptRoot) {
    $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    (Get-Location).Path
}
Set-Location $repoDir

$venvDir    = Join-Path $repoDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvPip    = Join-Path $venvDir "Scripts\pip.exe"

# ── Pick Python ───────────────────────────────────────────────────────────────
$python = $null
$pip    = $null

if (Test-Path $venvPython) {
    $python = $venvPython
    $pip    = $venvPip
} else {
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $ver = & $cmd --version 2>&1
            if ($ver -match "Python 3") {
                $python = $cmd
                $pip    = "pip"
                break
            }
        } catch { }
    }
}

if (-not $python) {
    Write-Host "[Code VM] ERROR: Python not found." -ForegroundColor Red
    Write-Host "  Run .\install.ps1 first, or install Python from https://python.org" -ForegroundColor Yellow
    Read-Host "  Press Enter to exit"
    exit 1
}

# ── Check if server is already running ───────────────────────────────────────
$listening = netstat -an 2>$null | Select-String ":$Port.*LISTEN"
if ($listening) {
    Write-Host "[Code VM] Server already running on port $Port." -ForegroundColor Green
    Start-Process "http://localhost:$Port"
    exit 0
}

# ── Install Flask if missing ──────────────────────────────────────────────────
$flaskOk = & $python -c "import flask" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[Code VM] Installing dependencies (first run)..." -ForegroundColor Cyan
    & $pip install flask requests --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[Code VM] ERROR: Failed to install dependencies." -ForegroundColor Red
        Write-Host "  Run .\install.ps1 first." -ForegroundColor Yellow
        Read-Host "  Press Enter to exit"
        exit 1
    }
}

# ── Resolve Ollama host URL and port from OLLAMA_HOST env var ────────────────
# server.py reads OLLAMA_HOST too — keep them in sync.
# Default: http://localhost:11434  Override: set OLLAMA_HOST=http://localhost:11435
if (-not $env:OLLAMA_HOST) { $env:OLLAMA_HOST = "http://localhost:11434" }
$ollamaPort = 11434
if ($env:OLLAMA_HOST -match ':(\d+)/?$') { $ollamaPort = [int]$Matches[1] }

# ── Auto-start Ollama if installed but not yet running ────────────────────────
$ollamaRunning  = $false
$ollamaInstalled = $false
try {
    $null = & ollama --version 2>&1
    if ($LASTEXITCODE -eq 0) { $ollamaInstalled = $true }
} catch { }

if ($ollamaInstalled) {
    $ollamaListening = netstat -an 2>$null | Select-String ":$ollamaPort.*LISTEN"
    if ($ollamaListening) {
        Write-Host "[Code VM] Ollama already running on port $ollamaPort." -ForegroundColor Green
        $ollamaRunning = $true
    } else {
        Write-Host "[Code VM] Starting Ollama service on port $ollamaPort..." -ForegroundColor Cyan
        # OLLAMA_HOST is already set in the environment so ollama serve picks it up
        Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Minimized
        # Wait up to 10 s for Ollama to start listening
        for ($i = 0; $i -lt 10; $i++) {
            Start-Sleep -Seconds 1
            $ollamaListening = netstat -an 2>$null | Select-String ":$ollamaPort.*LISTEN"
            if ($ollamaListening) { break }
        }
        if (netstat -an 2>$null | Select-String ":$ollamaPort.*LISTEN") {
            $ollamaRunning = $true
        } else {
            Write-Host "[Code VM] Warning: Ollama may not have started yet." -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "[Code VM] Ollama not installed — AI features disabled." -ForegroundColor Yellow
    Write-Host "           Install from https://ollama.com/download" -ForegroundColor DarkGray
}

# ── Use pythonw.exe (no-console Python) so server survives terminal closure ────
$pythonw = $python -replace 'python\.exe$', 'pythonw.exe'
if (-not (Test-Path $pythonw)) { $pythonw = $python }

# ── Start Flask server as a detached background process ──────────────────────
Write-Host "[Code VM] Starting server on port $Port ..." -ForegroundColor Cyan
$env:VM_PORT = "$Port"
Start-Process -FilePath $pythonw `
    -ArgumentList "vm\server.py" `
    -WorkingDirectory $repoDir

# ── Wait until server responds (up to 15 s) ───────────────────────────────────
Write-Host "[Code VM] Waiting for server to be ready..." -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:$Port/" -UseBasicParsing -TimeoutSec 2
        $ready = $true
        break
    } catch { }
}
if (-not $ready) {
    Write-Host "[Code VM] Warning: server may not be ready yet — opening browser anyway." -ForegroundColor Yellow
}

# ── Find local LAN IP ─────────────────────────────────────────────────────────
$localIP = $null
try {
    $localIP = (& $python -c @"
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
finally:
    s.close()
"@).Trim()
} catch { }
if (-not $localIP) { $localIP = $null }

# ── Add Windows Firewall rule (silent, best-effort) ──────────────────────────
try {
    $existing = Get-NetFirewallRule -DisplayName "Code VM (port $Port)" -ErrorAction SilentlyContinue
    if (-not $existing) {
        New-NetFirewallRule -DisplayName "Code VM (port $Port)" `
            -Direction Inbound -Protocol TCP -LocalPort $Port `
            -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null
    }
} catch { }

# ── Open browser ──────────────────────────────────────────────────────────────
Write-Host "[Code VM] Opening browser..." -ForegroundColor Cyan
Start-Process "http://localhost:$Port"

$sep = "  +----------------------------------------------------+"
Write-Host ""
Write-Host $sep -ForegroundColor Green
Write-Host ("  |  {0,-50}|" -f "Code VM is running!") -ForegroundColor Green
Write-Host ("  |{0}|" -f ("-" * 52)) -ForegroundColor DarkGreen
Write-Host ("  |  {0,-50}|" -f "This device:") -ForegroundColor Cyan
Write-Host ("  |    {0,-48}|" -f "http://localhost:$Port/") -ForegroundColor Cyan
Write-Host ("  |    {0,-48}|" -f "http://localhost:$Port/navigator/") -ForegroundColor Cyan
Write-Host ("  |{0}|" -f ("-" * 52)) -ForegroundColor DarkGreen
if ($localIP) {
    Write-Host ("  |  {0,-50}|" -f "Other devices on the same network:") -ForegroundColor Yellow
    Write-Host ("  |    {0,-48}|" -f "http://${localIP}:${Port}/") -ForegroundColor Yellow
    Write-Host ("  |    {0,-48}|" -f "http://${localIP}:${Port}/navigator/") -ForegroundColor Yellow
} else {
    Write-Host ("  |  {0,-50}|" -f "Other devices: run 'ipconfig' to find your IP,") -ForegroundColor Yellow
    Write-Host ("  |  {0,-50}|" -f "then open http://YOUR_IP:$Port/") -ForegroundColor Yellow
}
Write-Host ("  |{0}|" -f ("-" * 52)) -ForegroundColor DarkGreen
if ($ollamaRunning) {
    Write-Host ("  |  {0,-50}|" -f "Ollama AI:  running on port $ollamaPort  [OK]") -ForegroundColor Green
} elseif ($ollamaInstalled) {
    Write-Host ("  |  {0,-50}|" -f "Ollama AI:  installed — run 'ollama serve'") -ForegroundColor Yellow
} else {
    Write-Host ("  |  {0,-50}|" -f "Ollama AI:  not installed (https://ollama.com)") -ForegroundColor DarkGray
}
Write-Host ("  |  {0,-50}|" -f "Server runs in the background.") -ForegroundColor White
Write-Host ("  |  {0,-50}|" -f "This window can be closed safely.") -ForegroundColor White
Write-Host ("  |  {0,-50}|" -f "To stop: taskkill /f /im pythonw.exe") -ForegroundColor DarkGray
Write-Host $sep -ForegroundColor Green
Write-Host ""
