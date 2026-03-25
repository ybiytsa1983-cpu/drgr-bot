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
    # Prefer https if cert exists
    $certCheck = Join-Path $repoDir "ssl_cert.pem"
    $keyCheck  = Join-Path $repoDir "ssl_key.pem"
    $openScheme = if ((Test-Path $certCheck) -and (Test-Path $keyCheck)) { "https" } else { "http" }
    Start-Process "${openScheme}://localhost:$Port"
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

# -- Detect Ollama: honor OLLAMA_HOST if already set, then scan 11434-11444 --
# If OLLAMA_HOST is explicitly set in the environment, it is checked first.
# The port scan only runs if the configured URL is unreachable.
# This prevents overwriting a valid non-default port (e.g. 11435).
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

# Probe Ollama: if OLLAMA_HOST is explicitly set, try it first.
# Only scan ports 11434-11444 if the configured URL is not reachable.
# This prevents overwriting a valid non-default port (e.g. 11435) with whatever
# port responds first in the scan.
$detectedPort = $null
$detectedHost = $null
$userHostOk   = $false

if ($env:OLLAMA_HOST) {
    # Normalize: ensure http:// prefix
    $userUrl = $env:OLLAMA_HOST
    if ($userUrl -notmatch '^https?://') { $userUrl = "http://$userUrl" }
    try {
        $r = Invoke-WebRequest -Uri "$userUrl/api/tags" `
                -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($r -and $r.StatusCode -eq 200) {
            $userHostOk = $true
            # Normalize the env var (add http:// if missing)
            $env:OLLAMA_HOST = $userUrl
            if ($userUrl -match ':(\d+)/?$') { $ollamaPort = [int]$Matches[1] }
        }
    } catch { }
}

if (-not $userHostOk) {
    # Scan 127.0.0.1 first (avoids IPv6 issues on Windows where localhost → ::1).
    :portScan foreach ($tryHost in @("127.0.0.1", "localhost")) {
        foreach ($tryPort in (11434..11444)) {
            try {
                $r = Invoke-WebRequest -Uri "http://${tryHost}:$tryPort/api/tags" `
                        -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
                if ($r -and $r.StatusCode -eq 200) { $detectedPort = $tryPort; $detectedHost = $tryHost; break portScan }
            } catch { }
        }
    }
}

if ($userHostOk) {
    $ollamaRunning = $true
    Write-Host "[Code VM] Ollama running on $($env:OLLAMA_HOST) (OLLAMA_HOST)." -ForegroundColor Green
} elseif ($detectedPort) {
    $ollamaPort    = $detectedPort
    $ollamaRunning = $true
    $detectedUrl   = "http://${detectedHost}:${detectedPort}"
    if ($env:OLLAMA_HOST -and $env:OLLAMA_HOST -ne $detectedUrl) {
        Write-Host "[Code VM] OLLAMA_HOST ($($env:OLLAMA_HOST)) не отвечает — используется обнаруженный адрес $detectedUrl" -ForegroundColor Yellow
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

# -- Generate self-signed SSL certificate for HTTPS (LAN access fix) ----------
$certFile = Join-Path $repoDir "ssl_cert.pem"
$keyFile  = Join-Path $repoDir "ssl_key.pem"
$useHttps = $false
if (-not (Test-Path $certFile) -or -not (Test-Path $keyFile)) {
    try {
        $genResult = & $python -c @"
import sys, os
os.chdir(r'$($repoDir.Replace("\","\\"))')
try:
    from OpenSSL import crypto
    key = crypto.PKey()
    key.generate_key(crypto.TYPE_RSA, 2048)
    cert = crypto.X509()
    cert.get_subject().CN = 'Code VM'
    cert.set_serial_number(1)
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(365*24*60*60*10)  # 10 years
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(key)
    cert.sign(key, 'sha256')
    open('ssl_cert.pem','wb').write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
    open('ssl_key.pem','wb').write(crypto.dump_privatekey(crypto.FILETYPE_PEM, key))
    print('OK')
except Exception as e:
    print('SKIP:'+str(e))
"@ 2>&1
        if ($genResult -and $genResult.ToString().StartsWith('OK')) {
            Write-Host "[Code VM] SSL certificate generated for HTTPS." -ForegroundColor Green
        }
    } catch { }
}
if ((Test-Path $certFile) -and (Test-Path $keyFile)) {
    $env:VM_SSL_CERT = $certFile
    $env:VM_SSL_KEY  = $keyFile
    $useHttps = $true
    Write-Host "[Code VM] HTTPS mode enabled (self-signed cert)." -ForegroundColor Cyan
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

# -- Wait until server responds (up to 30 s) -----------------------------------
Write-Host "[Code VM] Waiting for server to be ready..." -ForegroundColor Cyan
$ready = $false
$pingScheme = if ($useHttps) { "https" } else { "http" }
# Disable SSL certificate validation for self-signed cert health check.
# PS6+ (PowerShell Core / PS7): Invoke-WebRequest has -SkipCertificateCheck.
# PS5.1 (.NET Framework): use ICertificatePolicy via Add-Type (more reliable
#   than the RemoteCertificateValidationCallback scriptblock cast).
if ($useHttps) {
    if ($PSVersionTable.PSVersion.Major -lt 6) {
        # PS5.1 path — Add-Type class is idempotent (ignored if already defined)
        try {
            Add-Type -TypeDefinition @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class _DrgrTrustAll : ICertificatePolicy {
    public bool CheckValidationResult(ServicePoint sp, X509Certificate cert,
        WebRequest req, int prob) { return true; }
}
"@ -ErrorAction SilentlyContinue
            [System.Net.ServicePointManager]::CertificatePolicy = New-Object _DrgrTrustAll
        } catch { }
        try {
            [System.Net.ServicePointManager]::ServerCertificateValidationCallback =
                [System.Net.Security.RemoteCertificateValidationCallback]{ param($s,$c,$ch,$e) $true }
        } catch { }
    }
    # PS7 path: -SkipCertificateCheck is added per-request in the loop below.
}
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        # Use /ping (instant, no Ollama query) so the check never races against
        # the 3-second Ollama timeout inside /health.
        # Use 127.0.0.1 (not localhost) to avoid IPv6 resolution on Windows.
        $iwrParams = @{
            Uri            = "${pingScheme}://127.0.0.1:$Port/ping"
            UseBasicParsing = $true
            TimeoutSec     = 10
        }
        # PS6+ supports -SkipCertificateCheck natively (ServicePointManager
        # is ignored by the HttpClient-based Invoke-WebRequest in PS7+).
        if ($useHttps -and $PSVersionTable.PSVersion.Major -ge 6) {
            $iwrParams['SkipCertificateCheck'] = $true
        }
        $null = Invoke-WebRequest @iwrParams
        $ready = $true
        break
    } catch [System.Net.WebException] {
        # Any HTTP response (even 4xx/5xx) means the server IS up.
        # TrustFailure / SecureChannelFailure = SSL cert error (self-signed) = server IS up.
        $wStatus = $_.Exception.Status
        if ($_.Exception.Response -ne $null -or
            $wStatus -eq [System.Net.WebExceptionStatus]::TrustFailure -or
            $wStatus -eq [System.Net.WebExceptionStatus]::SecureChannelFailure) {
            $ready = $true; break
        }
    } catch {
        # For non-WebException SSL/auth errors (e.g. AuthenticationException in PS7
        # when -SkipCertificateCheck is not supported), fall back to a raw TCP
        # port check so a running server is never incorrectly reported as failed.
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect('127.0.0.1', $Port)
            if ($tcp.Connected) { $ready = $true }
            $tcp.Close()
            if ($ready) { break }
        } catch { }
    }
}
if (-not $ready) {
    Write-Host ""
    Write-Host "[Code VM] ERROR: server did not start after 30 seconds!" -ForegroundColor Red
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

# -- Add Windows Firewall rule (try elevated first, then silent best-effort) --
$fwRuleName = "Code VM (port $Port)"
$fwCreated  = $false
try {
    $existing = Get-NetFirewallRule -DisplayName $fwRuleName -ErrorAction SilentlyContinue
    if (-not $existing) {
        New-NetFirewallRule -DisplayName $fwRuleName `
            -Direction Inbound -Protocol TCP -LocalPort $Port `
            -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null
        $fwCreated = $null -ne (Get-NetFirewallRule -DisplayName $fwRuleName -ErrorAction SilentlyContinue)
    } else { $fwCreated = $true }
} catch { }
if (-not $fwCreated -and $localIP) {
    # Fallback: try via netsh (sometimes works without elevation)
    try {
        $null = & netsh advfirewall firewall add rule name="$fwRuleName" `
            dir=in action=allow protocol=TCP localport=$Port 2>&1
        $fwCreated = $true
    } catch { }
}
if (-not $fwCreated) {
    Write-Host "[Code VM] Firewall: could not add rule automatically. Run as Admin or add manually:" -ForegroundColor Yellow
    Write-Host "  netsh advfirewall firewall add rule name=`"$fwRuleName`" dir=in action=allow protocol=TCP localport=$Port" -ForegroundColor Cyan
}

# When HTTPS is enabled, also open firewall for the HTTP redirect port (Port+1)
if ($useHttps) {
    $fwRuleHttp = "Code VM HTTP redirect (port $($Port+1))"
    try {
        $existingHttp = Get-NetFirewallRule -DisplayName $fwRuleHttp -ErrorAction SilentlyContinue
        if (-not $existingHttp) {
            New-NetFirewallRule -DisplayName $fwRuleHttp `
                -Direction Inbound -Protocol TCP -LocalPort ($Port + 1) `
                -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null
        }
    } catch {
        try {
            $null = & netsh advfirewall firewall add rule name="$fwRuleHttp" `
                dir=in action=allow protocol=TCP localport=$($Port+1) 2>&1
        } catch { }
    }
}

# -- Check LAN reachability (best-effort) --------------------------------------
$scheme = if ($useHttps) { "https" } else { "http" }
$lanReachable = $false
if ($localIP) {
    try {
        $lanIwrParams = @{
            Uri            = "${scheme}://${localIP}:${Port}/ping"
            UseBasicParsing = $true
            TimeoutSec     = 3
            ErrorAction    = 'SilentlyContinue'
        }
        if ($useHttps -and $PSVersionTable.PSVersion.Major -ge 6) {
            $lanIwrParams['SkipCertificateCheck'] = $true
        }
        $r = Invoke-WebRequest @lanIwrParams
        if ($r -and $r.StatusCode -eq 200) { $lanReachable = $true }
    } catch [System.Net.WebException] {
        if ($_.Exception.Response -ne $null) { $lanReachable = $true }
    } catch { }
    if ($lanReachable) {
        Write-Host "[Code VM] LAN check OK: ${scheme}://${localIP}:${Port}/" -ForegroundColor Green
    } else {
        Write-Host "[Code VM] LAN check: server not reachable on ${scheme}://${localIP}:${Port}/ — check firewall." -ForegroundColor Yellow
    }
}

# -- Open browser --------------------------------------------------------------
$browserUrl = "${scheme}://localhost:$Port"
Write-Host "[Code VM] Opening browser..." -ForegroundColor Cyan
Start-Process $browserUrl

$sep = "  +----------------------------------------------------+"
Write-Host ""
Write-Host $sep -ForegroundColor Green
Write-Host ("  |  {0,-50}|" -f "Code VM is running!") -ForegroundColor Green
Write-Host ("  |{0}|" -f ("-" * 52)) -ForegroundColor DarkGreen
Write-Host ("  |  {0,-50}|" -f "This device:") -ForegroundColor Cyan
Write-Host ("  |    {0,-48}|" -f "${scheme}://localhost:$Port/") -ForegroundColor Cyan
Write-Host ("  |{0}|" -f ("-" * 52)) -ForegroundColor DarkGreen
if ($localIP) {
    $lanStatus = if ($lanReachable -and $fwCreated) { "[OK]" } `
                 elseif ($lanReachable) { "[брандмауэр — см. ниже]" } `
                 else { "[недоступен — брандмауэр?]" }
    $lanColor  = if ($lanReachable -and $fwCreated) { "Green" } `
                 elseif ($lanReachable) { "Yellow" } `
                 else { "Red" }
    Write-Host ("  |  {0,-50}|" -f "Other devices on the same network:") -ForegroundColor Yellow
    Write-Host ("  |    {0,-48}|" -f "${scheme}://${localIP}:${Port}/  $lanStatus") -ForegroundColor $lanColor
    if ($useHttps) {
        $httpRedirPort = $Port + 1
        Write-Host ("  |  {0,-50}|" -f "📱 Телефон/планшет — используйте HTTP (без SSL):") -ForegroundColor Cyan
        Write-Host ("  |    {0,-48}|" -f "http://${localIP}:${httpRedirPort}/   (авто-редирект)") -ForegroundColor Cyan
        Write-Host ("  |  {0,-50}|" -f "ИЛИ откройте HTTPS и примите сертификат:") -ForegroundColor DarkGray
        Write-Host ("  |    {0,-48}|" -f "Chrome: Дополнительно → Перейти на сайт") -ForegroundColor DarkGray
        Write-Host ("  |    {0,-48}|" -f "Firefox: Принять риск и продолжить") -ForegroundColor DarkGray
    }
} else {
    Write-Host ("  |  {0,-50}|" -f "Other devices: run 'ipconfig' to find your IP,") -ForegroundColor Yellow
    Write-Host ("  |  {0,-50}|" -f "then open ${scheme}://YOUR_IP:$Port/") -ForegroundColor Yellow
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
if ($localIP -and -not $fwCreated) {
    Write-Host ("  |  {0,-50}|" -f "⚠ Другие устройства не могут подключиться?") -ForegroundColor Yellow
    Write-Host ("  |  {0,-50}|" -f "  Запусти в PowerShell от имени Администратора:") -ForegroundColor Yellow
    Write-Host ("  |    {0,-48}|" -f "netsh advfirewall firewall add rule") -ForegroundColor Cyan
    Write-Host ("  |    {0,-48}|" -f "  name=`"Code VM`" dir=in action=allow") -ForegroundColor Cyan
    Write-Host ("  |    {0,-48}|" -f "  protocol=TCP localport=$Port") -ForegroundColor Cyan
    Write-Host ("  |{0}|" -f ("-" * 52)) -ForegroundColor DarkGreen
}
Write-Host ("  |  {0,-50}|" -f "To restart from PowerShell:") -ForegroundColor White
Write-Host ("  |    {0,-48}|" -f "powershell -ExecutionPolicy Bypass -File") -ForegroundColor Cyan
Write-Host ("  |    {0,-48}|" -f "  `"$repoDir\start.ps1`"") -ForegroundColor Cyan
Write-Host $sep -ForegroundColor Green
Write-Host ""
