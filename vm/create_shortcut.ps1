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
    The shortcut points to start.bat in the repository root.
    You can also pin it to the taskbar by right-clicking and choosing
    "Pin to taskbar" after it appears on the Desktop.
#>

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

# Point the shortcut at start.bat in the repo root (the one-command launcher)
$batFile    = Join-Path $repoDir "start.bat"

if (-not (Test-Path $batFile)) {
    # Fallback to vm\start_vm.bat if start.bat is somehow missing
    $batFile = Join-Path $scriptDir "start_vm.bat"
    if (-not (Test-Path $batFile)) {
        Write-Error "Neither start.bat nor vm\start_vm.bat found."
        exit 1
    }
}

# -- Create the .lnk shortcut -------------------------------------------------
$desktopPath  = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "Code VM.lnk"

$shell    = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)

$shortcut.TargetPath       = $batFile
$shortcut.WorkingDirectory = $repoDir
$shortcut.Description      = "Launch Code VM - Monaco Editor with Ollama AI"
$shortcut.WindowStyle      = 1   # Normal window

# Use Python icon when available, otherwise fall back to cmd.exe icon
$pyCmd = Get-Command python  -ErrorAction SilentlyContinue
if (-not $pyCmd) { $pyCmd = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $pyCmd) { $pyCmd = Get-Command py      -ErrorAction SilentlyContinue }
if ($pyCmd) {
    $shortcut.IconLocation = "$($pyCmd.Source),0"
} else {
    $shortcut.IconLocation = "%SystemRoot%\System32\cmd.exe,0"
}

$shortcut.Save()

Write-Host ""
Write-Host "  [OK] Desktop shortcut created!" -ForegroundColor Green
Write-Host "       $shortcutPath" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Double-click 'Code VM' on your Desktop to launch the editor." -ForegroundColor Cyan
Write-Host "  The Monaco editor opens at http://localhost:5000" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Tip: right-click the shortcut -> 'Pin to taskbar'" -ForegroundColor Yellow
Write-Host ""

# -- Launch the server now so localhost:5000 is immediately reachable ---------
Write-Host "  [-->] Starting Code VM now..." -ForegroundColor Cyan
Start-Process -FilePath "cmd.exe" -ArgumentList "/k `"$batFile`"" -WorkingDirectory $repoDir
Write-Host "  [OK] Code VM is starting — browser will open in a few seconds." -ForegroundColor Green
Write-Host "       http://localhost:5000" -ForegroundColor Cyan
Write-Host ""
