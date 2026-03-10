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

# Also copy ЗАПУСТИТЬ.bat to Desktop as a backup/recovery launcher
$batSrc = Join-Path $repoDir 'ЗАПУСТИТЬ.bat'
if (Test-Path $batSrc) {
    try {
        Copy-Item -Path $batSrc -Destination (Join-Path $desktopPath 'ЗАПУСТИТЬ.bat') -Force
        Write-Host "  [OK] ЗАПУСТИТЬ.bat also placed on Desktop (backup launcher)." -ForegroundColor Green
    } catch { }
}
Write-Host ""
Write-Host "  Double-click 'Code VM' on your Desktop to launch the editor." -ForegroundColor Cyan
Write-Host "  The Monaco editor opens at http://localhost:5000" -ForegroundColor Cyan
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
