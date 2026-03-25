<#
.SYNOPSIS
    Stop the Code VM server.

.DESCRIPTION
    Stops the Flask server started by start.ps1 / vm.ps1.

    Usage:
        .\stop.ps1
    Or double-click stop.bat in Windows Explorer.
#>

# -- Resolve the directory containing this script ------------------------------
$scriptRoot = if ($PSScriptRoot) {
    $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    (Get-Location).Path
}

Set-Location $scriptRoot

$port = if ($env:VM_PORT) { [int]$env:VM_PORT } else { 5000 }
$stopped = $false

# -- Try PID file written by the server ----------------------------------------
$pidFile = Join-Path $scriptRoot "server.pid"
if (Test-Path $pidFile) {
    try {
        $pidContent = (Get-Content $pidFile -ErrorAction Stop).Trim()
        if ($pidContent -match '^\d+$') {
            $serverPid = [int]$pidContent
            if ($serverPid -gt 0) {
                Stop-Process -Id $serverPid -Force -ErrorAction Stop
                Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
                $stopped = $true
            }
        }
    } catch { }
}

# -- Fallback: find process listening on the VM port ---------------------------
if (-not $stopped) {
    try {
        $lines = & netstat -aon 2>$null | Select-String ":$port\s+.*LISTEN"
        foreach ($line in $lines) {
            $parts = ($line.ToString().Trim() -split '\s+')
            $pid2  = [int]$parts[-1]
            if ($pid2 -gt 0) {
                Stop-Process -Id $pid2 -Force -ErrorAction SilentlyContinue
                $stopped = $true
            }
        }
    } catch { }
}

if (Test-Path $pidFile) { Remove-Item $pidFile -Force -ErrorAction SilentlyContinue }

if ($stopped) {
    Write-Host " [OK] Code VM server stopped." -ForegroundColor Green
} else {
    Write-Host " [--] Code VM server was not running on port $port." -ForegroundColor Yellow
}
Write-Host ""
