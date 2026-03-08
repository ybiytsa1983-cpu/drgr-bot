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
    The shortcut points to vm\start_vm.bat inside the repository.
    You can also pin it to the taskbar by right-clicking and choosing
    "Pin to taskbar" after it appears on the Desktop.
#>

$ErrorActionPreference = "Stop"

# ── Resolve paths ─────────────────────────────────────────────────────────────
$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$batFile    = Join-Path $scriptDir "start_vm.bat"
$repoDir    = Split-Path -Parent $scriptDir

if (-not (Test-Path $batFile)) {
    Write-Error "start_vm.bat not found at: $batFile"
    exit 1
}

# ── Create the .lnk shortcut ──────────────────────────────────────────────────
$desktopPath  = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "Code VM.lnk"

$shell    = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)

$shortcut.TargetPath       = $batFile
$shortcut.WorkingDirectory = $repoDir
$shortcut.Description      = "Launch Code VM — Monaco Editor with Ollama AI"
$shortcut.WindowStyle      = 1   # Normal window

# Use Python icon when available (try python3 first, then python), otherwise fall back to cmd.exe icon
$pyCmd = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $pyCmd) { $pyCmd = Get-Command python -ErrorAction SilentlyContinue }
if ($pyCmd) {
    $shortcut.IconLocation = "$($pyCmd.Source),0"
} else {
    $shortcut.IconLocation = "%SystemRoot%\System32\cmd.exe,0"
}

$shortcut.Save()

Write-Host ""
Write-Host "  ✓  Desktop shortcut created!" -ForegroundColor Green
Write-Host "     $shortcutPath" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Double-click 'Code VM' on your Desktop to launch the editor." -ForegroundColor Cyan
Write-Host "  The Monaco editor opens at http://localhost:5000" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Tip: right-click the shortcut → 'Pin to taskbar' to keep it" -ForegroundColor Yellow
Write-Host "       in your taskbar as well." -ForegroundColor Yellow
Write-Host ""
