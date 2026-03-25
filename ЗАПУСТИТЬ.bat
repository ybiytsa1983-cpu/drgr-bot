<# 2>nul
@echo off
:: Try zapustit.ps1 next to this bat first (repo folder)
if exist "%~dp0zapustit.ps1" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0zapustit.ps1" %*
    exit /b
)
:: Not found here — search common repo locations
for %%D in (
    "%USERPROFILE%\drgr-bot"
    "%USERPROFILE%\Documents\drgr-bot"
    "%USERPROFILE%\Desktop\drgr-bot"
    "%USERPROFILE%\Downloads\drgr-bot"
    "%USERPROFILE%\projects\drgr-bot"
    "%USERPROFILE%\Projects\drgr-bot"
    "%USERPROFILE%\code\drgr-bot"
    "%USERPROFILE%\Code\drgr-bot"
    "%USERPROFILE%\repos\drgr-bot"
    "%USERPROFILE%\Repos\drgr-bot"
    "C:\drgr-bot"
    "C:\projects\drgr-bot"
    "C:\Projects\drgr-bot"
    "C:\code\drgr-bot"
    "C:\Code\drgr-bot"
    "C:\Users\%USERNAME%\drgr-bot"
    "D:\drgr-bot"
    "D:\projects\drgr-bot"
    "D:\Projects\drgr-bot"
    "D:\code\drgr-bot"
    "D:\Code\drgr-bot"
) do (
    if exist "%%~D\zapustit.ps1" (
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%%~D\zapustit.ps1" %*
        exit /b
    )
)
:: Not found — try auto-clone with git
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$dest = \"$env:USERPROFILE\drgr-bot\"; " ^
  "Write-Host ''; " ^
  "Write-Host '  Репозиторий drgr-bot не найден нигде. Цель: $dest' -ForegroundColor Yellow; " ^
  "if (Get-Command git -ErrorAction SilentlyContinue) { " ^
  "  if (Test-Path (Join-Path $dest '.git')) { " ^
  "    Write-Host '  Папка уже есть — обновляем (git pull)...' -ForegroundColor Cyan; " ^
  "    Push-Location $dest; git pull; Pop-Location " ^
  "  } elseif (Test-Path $dest) { " ^
  "    Write-Host '  Папка $dest существует без .git — клонируем заново...' -ForegroundColor Cyan; " ^
  "    Remove-Item $dest -Recurse -Force -ErrorAction SilentlyContinue; " ^
  "    git clone https://github.com/ybiytsa1983-cpu/drgr-bot \"$dest\" " ^
  "  } else { " ^
  "    Write-Host '  Клонируем репозиторий...' -ForegroundColor Cyan; " ^
  "    git clone https://github.com/ybiytsa1983-cpu/drgr-bot \"$dest\" " ^
  "  }; " ^
  "  $inst = Join-Path $dest 'install.ps1'; " ^
  "  if (-not (Test-Path $inst)) { " ^
  "    Write-Host '  Главная ветка пустая — ищем ветку с кодом...' -ForegroundColor Yellow; " ^
  "    Push-Location $dest; git fetch --all 2>`$null; " ^
  "    $brs = & git branch -r 2>`$null | Where-Object { `$_ -notmatch 'HEAD' } | ForEach-Object { `$_.Trim() -replace '^origin/','' }; " ^
  "    foreach (`$br in `$brs) { if (`$br -eq 'main') { continue }; `$null = & git checkout -B `$br \"origin/`$br\" --quiet 2>&1; if (Test-Path `$inst) { Write-Host \"  Нашли код на ветке: `$br\" -ForegroundColor Green; break } }; " ^
  "    Pop-Location " ^
  "  }; " ^
  "  $st   = Join-Path $dest 'start.ps1'; " ^
  "  if (Test-Path $inst) { Write-Host '  Установка зависимостей...' -ForegroundColor Cyan; Push-Location $dest; & $inst; Pop-Location }; " ^
  "  if (Test-Path $st) { Write-Host '  Запуск Code VM...' -ForegroundColor Green; Push-Location $dest; & $st } " ^
  "  else { Write-Host '  ОШИБКА: файлы не найдены после клонирования в $dest' -ForegroundColor Red; Read-Host '  Нажмите Enter для выхода' } " ^
  "} else { " ^
  "  Write-Host '' -ForegroundColor Red; " ^
  "  Write-Host '  ╔══════════════════════════════════════════════════════════╗' -ForegroundColor Red; " ^
  "  Write-Host '  ║  git НЕ УСТАНОВЛЕН — установи его ПЕРВЫМ                ║' -ForegroundColor Red; " ^
  "  Write-Host '  ╠══════════════════════════════════════════════════════════╣' -ForegroundColor Red; " ^
  "  Write-Host '  ║  1. Скачай Git: https://git-scm.com/download/win        ║' -ForegroundColor Yellow; " ^
  "  Write-Host '  ║  2. Установи (настройки по умолчанию — просто Next)     ║' -ForegroundColor Yellow; " ^
  "  Write-Host '  ║  3. Запусти этот файл снова                             ║' -ForegroundColor Yellow; " ^
  "  Write-Host '  ╚══════════════════════════════════════════════════════════╝' -ForegroundColor Red; " ^
  "  Write-Host ''; Read-Host '  Нажмите Enter для выхода' " ^
  "}"
exit /b
#>
# PowerShell fallback — runs when .bat is invoked directly from PS
$here = if ($PSScriptRoot) { $PSScriptRoot } `
        elseif ($MyInvocation.MyCommand.Path) { Split-Path $MyInvocation.MyCommand.Path } `
        else { (Get-Location).Path }
$zap = Join-Path $here 'zapustit.ps1'
if (Test-Path $zap) { & $zap @args; exit }
# zapustit.ps1 not beside this bat (e.g. bat is on Desktop) — search repo
foreach ($d in @(
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
)) {
    $zap = Join-Path $d 'zapustit.ps1'
    if (Test-Path $zap) { & $zap @args; exit }
}
# Repo not found anywhere — try auto-clone
Write-Host ''
Write-Host '  Репозиторий drgr-bot не найден нигде. Попытка клонирования...' -ForegroundColor Yellow
$dest = "$env:USERPROFILE\drgr-bot"
if (Get-Command git -ErrorAction SilentlyContinue) {
    if (Test-Path (Join-Path $dest '.git')) {
        Write-Host "  Папка уже есть — обновляем (git pull)..." -ForegroundColor Cyan
        Push-Location $dest
        git pull
        Pop-Location
    } elseif (Test-Path $dest) {
        Write-Host "  Папка $dest существует без .git — клонируем заново..." -ForegroundColor Cyan
        Remove-Item $dest -Recurse -Force -ErrorAction SilentlyContinue
        git clone https://github.com/ybiytsa1983-cpu/drgr-bot $dest
    } else {
        Write-Host "  git clone -> $dest" -ForegroundColor Cyan
        git clone https://github.com/ybiytsa1983-cpu/drgr-bot $dest
    }
    # If main is empty (pre-merge), find branch with the actual code
    $installPs = Join-Path $dest 'install.ps1'
    if (-not (Test-Path $installPs)) {
        Write-Host '  Главная ветка пустая — ищем ветку с кодом...' -ForegroundColor Yellow
        Push-Location $dest
        git fetch --all 2>$null
        $branches = & git branch -r 2>$null | Where-Object { $_ -notmatch 'HEAD' } |
            ForEach-Object { $_.Trim() -replace '^origin/', '' }
        foreach ($br in $branches) {
            if ($br -eq 'main') { continue }
            $null = & git checkout -B $br "origin/$br" --quiet 2>&1
            if (Test-Path $installPs) { Write-Host "  Нашли код на ветке: $br" -ForegroundColor Green; break }
        }
        Pop-Location
    }
    $startPs   = Join-Path $dest 'start.ps1'
    if (Test-Path $installPs) {
        Write-Host '  Установка зависимостей...' -ForegroundColor Cyan
        Push-Location $dest
        & $installPs
        Pop-Location
    }
    if (Test-Path $startPs) {
        Write-Host '  Запуск Code VM...' -ForegroundColor Green
        Push-Location $dest
        & $startPs
        exit
    } else {
        Write-Host "  ОШИБКА: start.ps1 не найден в $dest" -ForegroundColor Red
    }
} else {
    Write-Host ''
    Write-Host '  ╔══════════════════════════════════════════════════════════╗' -ForegroundColor Red
    Write-Host '  ║  git НЕ УСТАНОВЛЕН — установи его ПЕРВЫМ                ║' -ForegroundColor Red
    Write-Host '  ╠══════════════════════════════════════════════════════════╣' -ForegroundColor Red
    Write-Host '  ║  1. Скачай Git: https://git-scm.com/download/win        ║' -ForegroundColor Yellow
    Write-Host '  ║  2. Установи (настройки по умолчанию — просто Next)     ║' -ForegroundColor Yellow
    Write-Host '  ║  3. Запусти этот файл снова                             ║' -ForegroundColor Yellow
    Write-Host '  ╚══════════════════════════════════════════════════════════╝' -ForegroundColor Red
}
Write-Host ''
Read-Host '  Нажмите Enter для выхода'
exit 1
