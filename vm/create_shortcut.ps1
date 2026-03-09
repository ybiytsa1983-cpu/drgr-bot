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
    The shortcut runs start.bat via cmd.exe (works with any execution policy).
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

# Point the shortcut at start.bat - single step, no PowerShell dependency,
# works even if execution policy blocks .ps1 files.
$batFile = Join-Path $repoDir "start.bat"
if (-not (Test-Path $batFile)) {
    Write-Error "start.bat not found in $repoDir."
    exit 1
}

# -- Create the .lnk shortcut -------------------------------------------------
$desktopPath  = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "Code VM.lnk"

$shell    = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)

$shortcut.TargetPath   = $batFile
$shortcut.Arguments    = ""
$shortcut.IconLocation = "$env:SystemRoot\System32\cmd.exe,0"
$shortcut.WorkingDirectory = $repoDir
$shortcut.Description      = "Launch Code VM - Monaco Editor with Ollama AI"
$shortcut.WindowStyle      = 1   # Normal window

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
Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$batFile`"" -WorkingDirectory $repoDir
Write-Host "  [OK] Code VM is starting - browser will open in a few seconds." -ForegroundColor Green
Write-Host "       http://localhost:5000" -ForegroundColor Cyan
Write-Host ""
