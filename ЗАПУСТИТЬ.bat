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
  "Write-Host '  Репозиторий drgr-bot не найден. Пробуем клонировать...' -ForegroundColor Yellow; " ^
  "if (Get-Command git -ErrorAction SilentlyContinue) { " ^
  "  git clone https://github.com/ybiytsa1983-cpu/drgr-bot \"$dest\"; " ^
  "  $inst = Join-Path $dest 'install.ps1'; " ^
  "  $st   = Join-Path $dest 'start.ps1'; " ^
  "  if (Test-Path $inst) { Write-Host '  Установка...' -ForegroundColor Cyan; & $inst }; " ^
  "  if (Test-Path $st)   { Write-Host '  Запуск Code VM...' -ForegroundColor Green; & $st; exit } " ^
  "} else { " ^
  "  Write-Host '  git не найден. Скачайте: https://git-scm.com/download/win' -ForegroundColor Red; " ^
  "  Write-Host '  После установки запустите этот файл снова.' -ForegroundColor Yellow; " ^
  "  Write-Host ''; Read-Host '  Нажмите Enter для выхода' " ^
  "}"
exit /b 1
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
Write-Host '  Репозиторий drgr-bot не найден. Пробуем клонировать...' -ForegroundColor Yellow
$dest = "$env:USERPROFILE\drgr-bot"
if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-Host "  git clone -> $dest" -ForegroundColor Cyan
    git clone https://github.com/ybiytsa1983-cpu/drgr-bot $dest
    $installPs = Join-Path $dest 'install.ps1'
    $startPs   = Join-Path $dest 'start.ps1'
    if (Test-Path $installPs) {
        Write-Host '  Установка зависимостей...' -ForegroundColor Cyan
        & $installPs
    }
    if (Test-Path $startPs) {
        Write-Host '  Запуск Code VM...' -ForegroundColor Green
        & $startPs
        exit
    }
} else {
    Write-Host '  git не найден.' -ForegroundColor Red
    Write-Host '  1. Скачайте Git: https://git-scm.com/download/win' -ForegroundColor Yellow
    Write-Host '  2. После установки запустите этот файл снова.' -ForegroundColor Yellow
}
Write-Host ''
Read-Host '  Нажмите Enter для выхода'
exit 1
