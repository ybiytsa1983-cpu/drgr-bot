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
    "$env:USERPROFILE\repos\drgr-bot",
    "$env:USERPROFILE\Repos\drgr-bot",
    "C:\drgr-bot",
    "C:\projects\drgr-bot",
    "C:\Projects\drgr-bot",
    "C:\code\drgr-bot",
    "C:\Code\drgr-bot",
    "C:\Users\$env:USERNAME\drgr-bot",
    "D:\drgr-bot",
    "D:\projects\drgr-bot",
    "D:\Projects\drgr-bot",
    "D:\code\drgr-bot",
    "D:\Code\drgr-bot"
)
foreach ($d in $locations) {
    if ((Test-Path (Join-Path $d 'start.ps1')) -or (Test-Path (Join-Path $d 'start.bat'))) {
        $FOUND = $d; break
    }
}

if (-not $FOUND) {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        try {
            $top = & git -C $env:USERPROFILE rev-parse --show-toplevel 2>$null
            if ($top -and ((Test-Path (Join-Path $top 'start.ps1')) -or (Test-Path (Join-Path $top 'start.bat')))) { $FOUND = $top }
        } catch {}
    }
}

if (-not $FOUND) {
    Write-Host '  [Поиск] Ищем drgr-bot на C: и D:...' -ForegroundColor Cyan
    foreach ($root in @('C:\', 'D:\')) {
        Get-ChildItem $root -Filter 'drgr-bot' -Directory -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
            if (-not $FOUND -and ((Test-Path (Join-Path $_.FullName 'start.ps1')) -or (Test-Path (Join-Path $_.FullName 'start.bat')))) {
                $FOUND = $_.FullName
            }
        }
        if ($FOUND) { break }
    }
}

if (-not $FOUND) {
    # Repo not found anywhere — try auto-clone
    Write-Host ''
    Write-Host '  Репозиторий drgr-bot не найден. Попытка клонирования...' -ForegroundColor Yellow
    $dest = "$env:USERPROFILE\drgr-bot"
    if (Get-Command git -ErrorAction SilentlyContinue) {
        if (Test-Path (Join-Path $dest '.git')) {
            Write-Host "  Папка уже есть — обновляем (git pull)..." -ForegroundColor Cyan
            Push-Location $dest; git pull; Pop-Location
        } elseif (Test-Path $dest) {
            Write-Host "  Папка $dest существует без .git — клонируем заново..." -ForegroundColor Cyan
            Remove-Item $dest -Recurse -Force -ErrorAction SilentlyContinue
            git clone https://github.com/ybiytsa1983-cpu/drgr-bot $dest
        } else {
            Write-Host "  git clone -> $dest" -ForegroundColor Cyan
            git clone https://github.com/ybiytsa1983-cpu/drgr-bot $dest
        }
        # If main is empty/incomplete (pre-merge), switch to the dev branch
        $installPs = Join-Path $dest 'install.ps1'
        if (-not (Test-Path $installPs)) {
            Write-Host '  Главная ветка пустая — ищем ветку с кодом...' -ForegroundColor Yellow
            Push-Location $dest
            try {
                git fetch --all 2>$null
                $branches = & git branch -r 2>$null | Where-Object { $_ -notmatch 'HEAD' } |
                    ForEach-Object { $_.Trim() -replace '^origin/', '' }
                foreach ($br in $branches) {
                    if ($br -eq 'main') { continue }   # already tried main — it was empty
                    $null = & git checkout -B $br "origin/$br" --quiet 2>&1
                    if (Test-Path $installPs) {
                        Write-Host "  Нашли код на ветке: $br" -ForegroundColor Green
                        break
                    }
                }
            } finally { Pop-Location }
        }
        $startPs   = Join-Path $dest 'start.ps1'
        if (Test-Path $installPs) {
            Write-Host '  Установка зависимостей...' -ForegroundColor Cyan
            Push-Location $dest; & $installPs; Pop-Location
        }
        if (Test-Path $startPs) {
            Write-Host '  Запуск Code VM...' -ForegroundColor Green
            Push-Location $dest; & $startPs; exit
        } else {
            Write-Host "  ОШИБКА: start.ps1 не найден в $dest" -ForegroundColor Red
        }
    } else {
        Write-Host ''
        Write-Host '  ╔══════════════════════════════════════════════════════════════╗' -ForegroundColor Red
        Write-Host '  ║  ПАПКА drgr-bot НЕ НАЙДЕНА и git не установлен              ║' -ForegroundColor Red
        Write-Host '  ╠══════════════════════════════════════════════════════════════╣' -ForegroundColor Red
        Write-Host '  ║  1. Установи Git: https://git-scm.com/download/win          ║' -ForegroundColor Yellow
        Write-Host '  ║  2. После установки запусти этот файл снова                 ║' -ForegroundColor Yellow
        Write-Host '  ╚══════════════════════════════════════════════════════════════╝' -ForegroundColor Red
        Write-Host ''
        Write-Host '  ИЛИ вставь в PowerShell (Win+X → Windows PowerShell):' -ForegroundColor Cyan
        $iwr = 'irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/ZAPУСТИТЬ.bat" -OutFile "$env:USERPROFILE\Desktop\ЗАПУСТИТЬ.bat"; & "$env:USERPROFILE\Desktop\ЗАПУСТИТЬ.bat"'
        Write-Host "  $iwr" -ForegroundColor White
    }
    Write-Host ''
    Read-Host '  Нажмите Enter для выхода'
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

# Also copy ЗАПУСТИТЬ.bat + zapustit.ps1 to Desktop as backup/recovery launchers
try {
    $batSrc = Join-Path $FOUND 'ЗАПУСТИТЬ.bat'
    if (Test-Path $batSrc) {
        Copy-Item -Path $batSrc -Destination (Join-Path $desktop 'ЗАПУСТИТЬ.bat') -Force
        Write-Host '  [OK] ЗАПУСТИТЬ.bat copied to Desktop (backup launcher).' -ForegroundColor Green
    }
} catch { Write-Host "  [!] Could not copy ЗАПУСТИТЬ.bat: $_" -ForegroundColor Yellow }
try {
    $zapSrc = Join-Path $FOUND 'zapustit.ps1'
    if (Test-Path $zapSrc) {
        Copy-Item -Path $zapSrc -Destination (Join-Path $desktop 'zapustit.ps1') -Force
    }
} catch { }
# Copy VM launchers to Desktop
try {
    $vmBat = Join-Path $FOUND 'ЗАПУСТИТЬ_ВМ.bat'
    if (Test-Path $vmBat) {
        Copy-Item -Path $vmBat -Destination (Join-Path $desktop 'ЗАПУСТИТЬ_ВМ.bat') -Force
        Write-Host '  [OK] ЗАПУСТИТЬ_ВМ.bat copied to Desktop.' -ForegroundColor Green
    }
} catch { }
try {
    $retrainBat = Join-Path $FOUND 'ПЕРЕУЧИТЬ_ВМ.bat'
    if (Test-Path $retrainBat) {
        Copy-Item -Path $retrainBat -Destination (Join-Path $desktop 'ПЕРЕУЧИТЬ_ВМ.bat') -Force
        Write-Host '  [OK] ПЕРЕУЧИТЬ_ВМ.bat copied to Desktop.' -ForegroundColor Green
    }
} catch { }

# ── Start Ollama early so it is ready when the VM server connects ─────────────
Write-Host '  [Ollama] Checking Ollama...' -ForegroundColor Cyan
$ollamaExe = $null
# Try PATH first
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaCmd) { $ollamaExe = $ollamaCmd.Source }
# Fall back to common install locations
if (-not $ollamaExe) {
    foreach ($c in @(
        "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
        "$env:USERPROFILE\AppData\Local\Programs\Ollama\ollama.exe",
        "C:\Program Files\Ollama\ollama.exe",
        "C:\Program Files (x86)\Ollama\ollama.exe"
    )) {
        if (Test-Path $c) { $ollamaExe = $c; break }
    }
}
if ($ollamaExe) {
    # Check if already running
    $ollamaUp = $false
    foreach ($tryPort in (11434..11444)) {
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:$tryPort/api/tags" `
                    -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
            if ($r -and $r.StatusCode -eq 200) { $ollamaUp = $true; break }
        } catch {}
    }
    if (-not $ollamaUp) {
        Write-Host '  [Ollama] Starting ollama serve...' -ForegroundColor Cyan
        Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Minimized -ErrorAction SilentlyContinue
        # Brief wait — vm.ps1 will wait longer if needed
        Start-Sleep -Seconds 2
        Write-Host '  [OK] Ollama service starting in background.' -ForegroundColor Green
    } else {
        Write-Host '  [OK] Ollama already running.' -ForegroundColor Green
    }
} else {
    Write-Host '  [~] Ollama not found — AI features will be disabled.' -ForegroundColor Yellow
    Write-Host '      Download from https://ollama.com/download' -ForegroundColor DarkGray
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
