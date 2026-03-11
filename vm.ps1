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

# -- Pick Python ---------------------------------------------------------------
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

# -- Check if server is already running ---------------------------------------
$listening = netstat -an 2>$null | Select-String ":$Port.*LISTEN"
if ($listening) {
    Write-Host "[Code VM] Server already running on port $Port." -ForegroundColor Green
    Start-Process "http://localhost:$Port"
    exit 0
}

# -- Install Flask if missing --------------------------------------------------
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

# -- Detect Ollama: scan ports 11434-11444 first, then fall back to default ---
# This correctly handles users who run Ollama on a non-default port (e.g. 11435)
# without requiring them to manually set OLLAMA_HOST.
$ollamaRunning   = $false
$ollamaInstalled = $false
$ollamaPort      = 11434
$ollamaExePath   = $null   # full path to ollama.exe (or 'ollama' if in PATH)

$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaCmd) {
    $ollamaInstalled = $true
    $ollamaExePath   = $ollamaCmd.Source
}

# If not in PATH, check common Windows install locations
if (-not $ollamaInstalled) {
    $ollamaCandidates = @(
        "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
        "$env:USERPROFILE\AppData\Local\Programs\Ollama\ollama.exe",
        "C:\Program Files\Ollama\ollama.exe",
        "C:\Program Files (x86)\Ollama\ollama.exe"
    )
    foreach ($c in $ollamaCandidates) {
        if (Test-Path $c) {
            $ollamaInstalled = $true
            $ollamaExePath   = $c
            break
        }
    }
}

# Probe ports 11434-11444 to find an already-running Ollama instance
# Scan 127.0.0.1 first (avoids IPv6 issues on Windows where localhost → ::1).
$detectedPort = $null
$detectedHost = $null
:portScan foreach ($tryHost in @("127.0.0.1", "localhost")) {
    foreach ($tryPort in (11434..11444)) {
        try {
            $r = Invoke-WebRequest -Uri "http://${tryHost}:$tryPort/api/tags" `
                    -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
            if ($r -and $r.StatusCode -eq 200) { $detectedPort = $tryPort; $detectedHost = $tryHost; break portScan }
        } catch { }
    }
}

if ($detectedPort) {
    $ollamaPort    = $detectedPort
    $ollamaRunning = $true
    $detectedUrl   = "http://${detectedHost}:${detectedPort}"
    # Always sync OLLAMA_HOST to the actual detected URL so server.py uses the right address.
    if ($env:OLLAMA_HOST -and $env:OLLAMA_HOST -ne $detectedUrl) {
        Write-Host "[Code VM] Updating OLLAMA_HOST from $($env:OLLAMA_HOST) to detected $detectedUrl" -ForegroundColor Yellow
    }
    $env:OLLAMA_HOST = $detectedUrl
    Write-Host "[Code VM] Ollama already running on $detectedUrl." -ForegroundColor Green
} else {
    # Ollama not detected — fall back to configured / default port
    if (-not $env:OLLAMA_HOST) { $env:OLLAMA_HOST = "http://localhost:11434" }
    if ($env:OLLAMA_HOST -match ':(\d+)/?$') { $ollamaPort = [int]$Matches[1] }
    if ($ollamaInstalled) {
        Write-Host "[Code VM] Starting Ollama service on port $ollamaPort..." -ForegroundColor Cyan
        # OLLAMA_HOST is already set so ollama serve listens on the correct port
        Start-Process -FilePath $ollamaExePath -ArgumentList "serve" -WindowStyle Minimized
        # Wait up to 10 s for Ollama to respond — probe both 127.0.0.1 and localhost
        for ($i = 0; $i -lt 10; $i++) {
            Start-Sleep -Seconds 1
            $started = $false
            foreach ($wh in @("127.0.0.1", "localhost")) {
                try {
                    $r = Invoke-WebRequest -Uri "http://${wh}:$ollamaPort/api/tags" `
                            -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
                    if ($r -and $r.StatusCode -eq 200) { $ollamaRunning = $true; $started = $true; break }
                } catch { }
            }
            if ($started) { break }
        }
        if (-not $ollamaRunning) {
            Write-Host "[Code VM] Warning: Ollama may not have started yet." -ForegroundColor Yellow
        }
    } else {
        Write-Host "[Code VM] Ollama not installed - AI features disabled." -ForegroundColor Yellow
        Write-Host "           Install from https://ollama.com/download" -ForegroundColor DarkGray
    }
}

# -- Start Flask server and capture output for diagnostics --------------------
Write-Host "[Code VM] Starting server on port $Port ..." -ForegroundColor Cyan
$env:VM_PORT = "$Port"
$logPath = Join-Path $repoDir "server.log"
$errPath = Join-Path $repoDir "server_err.log"
# Clear stale logs so fresh errors are immediately visible
Remove-Item $logPath -Force -ErrorAction SilentlyContinue
Remove-Item $errPath -Force -ErrorAction SilentlyContinue
Start-Process -FilePath $python `
    -ArgumentList "vm\server.py" `
    -WorkingDirectory $repoDir `
    -RedirectStandardOutput $logPath `
    -RedirectStandardError  $errPath `
    -NoNewWindow

# -- Wait until server responds (up to 20 s) -----------------------------------
Write-Host "[Code VM] Waiting for server to be ready..." -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    try {
        # Use /ping (instant, no Ollama query) so the check never races against
        # the 3-second Ollama timeout inside /health.
        # Use 127.0.0.1 (not localhost) to avoid IPv6 resolution on Windows.
        $null = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/ping" -UseBasicParsing -TimeoutSec 10
        $ready = $true
        break
    } catch [System.Net.WebException] {
        # Any HTTP response (even 4xx/5xx) means the server IS up.
        if ($_.Exception.Response -ne $null) { $ready = $true; break }
    } catch { }
}
if (-not $ready) {
    Write-Host ""
    Write-Host "[Code VM] ERROR: server did not start after 20 seconds!" -ForegroundColor Red
    Write-Host ""
    # Show combined log and error output
    $combined = @()
    if (Test-Path $logPath) { $combined += Get-Content $logPath }
    if (Test-Path $errPath) { $combined += Get-Content $errPath }
    if ($combined) {
        Write-Host "--- server output ---" -ForegroundColor Yellow
        $combined | ForEach-Object { Write-Host $_ }
        Write-Host "---------------------" -ForegroundColor Yellow
    } else {
        Write-Host "(no server output captured)" -ForegroundColor Yellow
        Write-Host "Retrying with visible python.exe window..." -ForegroundColor Cyan
        Start-Process -FilePath $python -ArgumentList "vm\server.py" -WorkingDirectory $repoDir
        Start-Sleep -Seconds 5
    }
    Write-Host ""
    Write-Host "Fix the error above then run .\start.ps1 again." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  # To restart, paste this command:" -ForegroundColor White
    Write-Host "    powershell -ExecutionPolicy Bypass -File `"$repoDir\start.ps1`"" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Tip: .venv\Scripts\pip install flask requests" -ForegroundColor Cyan
    Read-Host "Press Enter to exit"
    exit 1
}

# -- Find local LAN IP ---------------------------------------------------------
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

# -- Add Windows Firewall rule (silent, best-effort) --------------------------
try {
    $existing = Get-NetFirewallRule -DisplayName "Code VM (port $Port)" -ErrorAction SilentlyContinue
    if (-not $existing) {
        New-NetFirewallRule -DisplayName "Code VM (port $Port)" `
            -Direction Inbound -Protocol TCP -LocalPort $Port `
            -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null
    }
} catch { }

# -- Check LAN reachability (best-effort) --------------------------------------
$lanReachable = $false
if ($localIP) {
    try {
        $r = Invoke-WebRequest -Uri "http://${localIP}:${Port}/ping" `
                -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($r -and $r.StatusCode -eq 200) { $lanReachable = $true }
    } catch [System.Net.WebException] {
        if ($_.Exception.Response -ne $null) { $lanReachable = $true }
    } catch { }
    if ($lanReachable) {
        Write-Host "[Code VM] LAN check OK: http://${localIP}:${Port}/" -ForegroundColor Green
    } else {
        Write-Host "[Code VM] LAN check: server not reachable on http://${localIP}:${Port}/ — check firewall." -ForegroundColor Yellow
    }
}

# -- Open browser --------------------------------------------------------------
Write-Host "[Code VM] Opening browser..." -ForegroundColor Cyan
Start-Process "http://localhost:$Port"

$sep = "  +----------------------------------------------------+"
Write-Host ""
Write-Host $sep -ForegroundColor Green
Write-Host ("  |  {0,-50}|" -f "Code VM is running!") -ForegroundColor Green
Write-Host ("  |{0}|" -f ("-" * 52)) -ForegroundColor DarkGreen
Write-Host ("  |  {0,-50}|" -f "This device:") -ForegroundColor Cyan
Write-Host ("  |    {0,-48}|" -f "http://localhost:$Port/") -ForegroundColor Cyan
Write-Host ("  |{0}|" -f ("-" * 52)) -ForegroundColor DarkGreen
if ($localIP) {
    $lanStatus = if ($lanReachable) { "[OK]" } else { "[недоступен — брандмауэр?]" }
    $lanColor  = if ($lanReachable) { "Green" } else { "Yellow" }
    Write-Host ("  |  {0,-50}|" -f "Other devices on the same network:") -ForegroundColor Yellow
    Write-Host ("  |    {0,-48}|" -f "http://${localIP}:${Port}/  $lanStatus") -ForegroundColor $lanColor
} else {
    Write-Host ("  |  {0,-50}|" -f "Other devices: run 'ipconfig' to find your IP,") -ForegroundColor Yellow
    Write-Host ("  |  {0,-50}|" -f "then open http://YOUR_IP:$Port/") -ForegroundColor Yellow
}
Write-Host ("  |{0}|" -f ("-" * 52)) -ForegroundColor DarkGreen
if ($ollamaRunning) {
    Write-Host ("  |  {0,-50}|" -f "Ollama AI:  running on port $ollamaPort  [OK]") -ForegroundColor Green
} elseif ($ollamaInstalled) {
    Write-Host ("  |  {0,-50}|" -f "Ollama AI:  installed - run 'ollama serve'") -ForegroundColor Yellow
} else {
    Write-Host ("  |  {0,-50}|" -f "Ollama AI:  not installed (https://ollama.com)") -ForegroundColor DarkGray
}
Write-Host ("  |  {0,-50}|" -f "Server runs in the background.") -ForegroundColor White
Write-Host ("  |  {0,-50}|" -f "This window can be closed safely.") -ForegroundColor White
Write-Host ("  |  {0,-50}|" -f "To stop: double-click stop.bat") -ForegroundColor DarkGray
Write-Host ("  |{0}|" -f ("-" * 52)) -ForegroundColor DarkGreen
Write-Host ("  |  {0,-50}|" -f "To restart from PowerShell:") -ForegroundColor White
Write-Host ("  |    {0,-48}|" -f "powershell -ExecutionPolicy Bypass -File") -ForegroundColor Cyan
Write-Host ("  |    {0,-48}|" -f "  `"$repoDir\start.ps1`"") -ForegroundColor Cyan
Write-Host $sep -ForegroundColor Green
Write-Host ""
