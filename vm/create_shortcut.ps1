<#
.SYNOPSIS
    Creates a "Code VM" desktop shortcut on Windows.

.DESCRIPTION
    Run this script once to install a "Code VM" icon on your Desktop.
    Double-clicking the icon will start the Flask server and open the
    Monaco Editor in your default browser automatically.

    Usage (from PowerShell or Windows Terminal):
        powershell -ExecutionPolicy Bypass -File vm\create_shortcut.ps1

.NOTES
    The shortcut runs powershell.exe -File start.ps1 (bypasses .bat file
    association issues on Windows 11 with Windows Terminal).
    You can also pin it to the taskbar by right-clicking and choosing
    "Pin to taskbar" after it appears on the Desktop.
#>
param(
    # Pass -NoLaunch to create/update the shortcut without starting the server.
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"

# -- Resolve paths -------------------------------------------------------------
# $PSScriptRoot is empty when PS is invoked without -File (e.g.
# "powershell vm\create_shortcut.ps1" instead of
# "powershell -File vm\create_shortcut.ps1").
# Fall back to $MyInvocation, then to the current working directory.
$scriptDir = if ($PSScriptRoot) {
    $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    (Get-Location).Path
}
$repoDir    = Split-Path -Parent $scriptDir

# Point the shortcut at powershell.exe running start.ps1 directly.
# Targeting start.bat can fail on Windows 11 when Windows Terminal is the
# default terminal: it opens the .bat shortcut in a PS profile instead of
# cmd.exe, causing PowerShell to parse batch syntax (%~dp0 not expanded).
$startPs1 = Join-Path $repoDir "start.ps1"
if (-not (Test-Path $startPs1)) {
    Write-Error "start.ps1 not found in $repoDir."
    exit 1
}
$psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path $psExe)) { $psExe = "powershell.exe" }

# -- Create the .lnk shortcut -------------------------------------------------
$desktopPath  = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "Code VM.lnk"

$shell    = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)

$shortcut.TargetPath       = $psExe
$shortcut.Arguments        = "-NoProfile -ExecutionPolicy Bypass -File `"$startPs1`""
# Prefer bundled custom icon; fall back to a reliably-visible system icon
$customIco = Join-Path $repoDir "vm\static\code_vm.ico"
if (Test-Path $customIco) {
    $shortcut.IconLocation = "$customIco,0"
} else {
    $icoLib = Join-Path $env:SystemRoot "System32\shell32.dll"
    $shortcut.IconLocation     = if (Test-Path $icoLib) { "$icoLib,77" } else { "$psExe,0" }
}
$shortcut.WorkingDirectory = $repoDir
$shortcut.Description      = "Launch Code VM - Monaco Editor with Ollama AI"
$shortcut.WindowStyle      = 1   # Normal window so progress and errors are visible

$shortcut.Save()

Write-Host ""
Write-Host "  [OK] Desktop shortcut created!" -ForegroundColor Green
Write-Host "       $shortcutPath" -ForegroundColor DarkGray

# Also copy launcher bat files to Desktop for easy access
$batSrc = Join-Path $repoDir 'ЗАПУСТИТЬ.bat'
if (Test-Path $batSrc) {
    try {
        Copy-Item -Path $batSrc -Destination (Join-Path $desktopPath 'ЗАПУСТИТЬ.bat') -Force
        Write-Host "  [OK] ЗАПУСТИТЬ.bat also placed on Desktop (backup launcher)." -ForegroundColor Green
    } catch { }
}
# Copy ЗАПУСТИТЬ_ВМ.bat (launches VM + auto-creates drgr-visor retrained model)
$vmBatSrc = Join-Path $repoDir 'ЗАПУСТИТЬ_ВМ.bat'
if (Test-Path $vmBatSrc) {
    try {
        Copy-Item -Path $vmBatSrc -Destination (Join-Path $desktopPath 'ЗАПУСТИТЬ_ВМ.bat') -Force
        Write-Host "  [OK] ЗАПУСТИТЬ_ВМ.bat placed on Desktop (VM + retrained model)." -ForegroundColor Green
    } catch { }
}
# Copy ПЕРЕУЧИТЬ_ВМ.bat (re-trains / recreates the drgr-visor model)
$retrainBatSrc = Join-Path $repoDir 'ПЕРЕУЧИТЬ_ВМ.bat'
if (Test-Path $retrainBatSrc) {
    try {
        Copy-Item -Path $retrainBatSrc -Destination (Join-Path $desktopPath 'ПЕРЕУЧИТЬ_ВМ.bat') -Force
        Write-Host "  [OK] ПЕРЕУЧИТЬ_ВМ.bat placed on Desktop (retrain model)." -ForegroundColor Green
    } catch { }
}
# Copy ОБНОВИТЬ.bat (update repo + pip dependencies)
$updateBatSrc = Join-Path $repoDir 'ОБНОВИТЬ.bat'
if (Test-Path $updateBatSrc) {
    try {
        Copy-Item -Path $updateBatSrc -Destination (Join-Path $desktopPath 'ОБНОВИТЬ.bat') -Force
        Write-Host "  [OK] ОБНОВИТЬ.bat placed on Desktop (update / git pull)." -ForegroundColor Green
    } catch { }
}
Write-Host ""
Write-Host "  Double-click 'Code VM' on your Desktop to launch the editor." -ForegroundColor Cyan
Write-Host "  The Monaco editor opens at http://localhost:5000" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Launcher files on Desktop:" -ForegroundColor Yellow
Write-Host "    Code VM.lnk       — main shortcut (start.ps1)" -ForegroundColor DarkGray
Write-Host "    ЗАПУСТИТЬ_ВМ.bat  — VM + auto-create drgr-visor retrained model" -ForegroundColor DarkGray
Write-Host "    ПЕРЕУЧИТЬ_ВМ.bat  — recreate/update drgr-visor model only" -ForegroundColor DarkGray
Write-Host "    ЗАПУСТИТЬ.bat     — basic launcher (backup)" -ForegroundColor DarkGray
Write-Host "    ОБНОВИТЬ.bat      — update files (git pull + pip install)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Tip: right-click the shortcut -> 'Pin to taskbar'" -ForegroundColor Yellow
Write-Host ""

# -- Launch the server now so localhost:5000 is immediately reachable ---------
# Skip auto-launch when called with -NoLaunch (e.g. from install.ps1 or repair runs).
if (-not $NoLaunch) {
    Write-Host "  [-->] Starting Code VM now..." -ForegroundColor Cyan
    Start-Process -FilePath $psExe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$startPs1`"" -WorkingDirectory $repoDir
    Write-Host "  [OK] Code VM is starting - browser will open in a few seconds." -ForegroundColor Green
    Write-Host "       http://localhost:5000" -ForegroundColor Cyan
    Write-Host ""
}
