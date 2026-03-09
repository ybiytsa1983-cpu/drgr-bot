# ZAPUSTIT.ps1 - avtomaticheskij zapusk Code VM
# UTF-8 BOM required for Russian Windows
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try { $host.UI.RawUI.WindowTitle = 'Code VM - Zapusk...' } catch {}

$FOUND = $null
$locations = @(
    "$env:USERPROFILE\drgr-bot",
    "$env:USERPROFILE\Documents\drgr-bot",
    "$env:USERPROFILE\Desktop\drgr-bot",
    "$env:USERPROFILE\Downloads\drgr-bot",
    "$env:USERPROFILE\projects\drgr-bot",
    "$env:USERPROFILE\Projects\drgr-bot",
    "$env:USERPROFILE\code\drgr-bot",
    "$env:USERPROFILE\Code\drgr-bot",
    "C:\drgr-bot",
    "C:\projects\drgr-bot",
    "C:\Projects\drgr-bot",
    "C:\code\drgr-bot",
    "C:\Code\drgr-bot",
    "C:\Users\$env:USERNAME\drgr-bot",
    "D:\drgr-bot",
    "D:\projects\drgr-bot"
)
foreach ($d in $locations) {
    if (Test-Path (Join-Path $d 'start.bat')) {
        $FOUND = $d; break
    }
}

if (-not $FOUND) {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        try {
            $top = & git -C $env:USERPROFILE rev-parse --show-toplevel 2>$null
            if ($top -and (Test-Path (Join-Path $top 'start.bat'))) { $FOUND = $top }
        } catch {}
    }
}

if (-not $FOUND) {
    Write-Host '  [Poisk] Ishchem drgr-bot na C:...' -ForegroundColor Cyan
    foreach ($root in @('C:\', 'D:\')) {
        Get-ChildItem $root -Filter 'drgr-bot' -Directory -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
            if (-not $FOUND -and (Test-Path (Join-Path $_.FullName 'start.bat'))) {
                $FOUND = $_.FullName
            }
        }
        if ($FOUND) { break }
    }
}

if (-not $FOUND) {
    Write-Host '' 
    Write-Host '  ERROR: drgr-bot folder not found.' -ForegroundColor Red
    Write-Host '' 
    Write-Host '  Open PowerShell (Win+X) and run:' -ForegroundColor White
    Write-Host "    cd `"$env:USERPROFILE`"; git clone https://github.com/ybiytsa1983-cpu/drgr-bot; cd drgr-bot; powershell -ExecutionPolicy Bypass -File install.ps1" -ForegroundColor Yellow
    Write-Host '' 
    Read-Host 'Press Enter to exit'
    exit 1
}

Write-Host '' 
Write-Host "  [OK] Found: $FOUND" -ForegroundColor Green
Write-Host '' 

Set-Location $FOUND

Write-Host '  [Update] Pulling latest fixes...' -ForegroundColor Cyan
if (Test-Path (Join-Path $FOUND '.git')) {
    try { $null = & git pull --ff-only --quiet 2>&1; Write-Host '  [OK] Update done.' -ForegroundColor Green }
    catch { Write-Host '  [OK] Update skipped (no network).' -ForegroundColor Yellow }
} else {
    Write-Host '  [OK] Not a git repo, skipping.' -ForegroundColor Yellow
}

Write-Host '  [CRLF] Normalizing .bat line endings...' -ForegroundColor Cyan
Get-ChildItem $FOUND -Recurse -Filter '*.bat' | ForEach-Object {
    $p = $_.FullName
    try {
        $bytes = [System.IO.File]::ReadAllBytes($p)
        $text  = [System.Text.Encoding]::Default.GetString($bytes)
        $fixed = ($text -replace "`r", '') -replace "`n", "`r`n"
        if ($text -ne $fixed) { [System.IO.File]::WriteAllText($p, $fixed, [System.Text.Encoding]::Default) }
    } catch {}
}
Write-Host '  [OK] CRLF normalization done.' -ForegroundColor Green

Write-Host '  [Shortcut] Updating Desktop shortcut...' -ForegroundColor Cyan
try {
    $desktop  = [Environment]::GetFolderPath('Desktop')
    $startPs1 = Join-Path $FOUND 'start.ps1'
    $psExe    = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path $psExe)) { $psExe = 'powershell.exe' }
    $sh  = New-Object -COM WScript.Shell
    $lnk = $sh.CreateShortcut((Join-Path $desktop 'Code VM.lnk'))
    $lnk.TargetPath       = $psExe
    $lnk.Arguments        = "-NoProfile -ExecutionPolicy Bypass -File `"$startPs1`""
    $lnk.WorkingDirectory = $FOUND
    $lnk.Description      = 'Launch Code VM - Monaco Editor with Ollama AI'
    $lnk.WindowStyle      = 1
    $lnk.IconLocation     = "$psExe,0"
    $lnk.Save()
    Write-Host '  [OK] Code VM shortcut updated on Desktop.' -ForegroundColor Green
} catch {
    Write-Host "  [!] Shortcut not created: $_" -ForegroundColor Yellow
}

Write-Host '' 
Write-Host '  [Launch] Starting Code VM...' -ForegroundColor Green
Write-Host '' 
$startPs = Join-Path $FOUND 'start.ps1'
if (Test-Path $startPs) {
    & $startPs
} else {
    & cmd /c (Join-Path $FOUND 'start.bat')
}
