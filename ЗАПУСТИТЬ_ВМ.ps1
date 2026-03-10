# ЗАПУСТИТЬ_ВМ.ps1 — запуск Code VM с переученной моделью drgr-visor (qwen3-vl:8b)
#
# Что делает этот скрипт:
#   1. Запускает Code VM (Flask сервер на порту 5000)
#   2. Создаёт ярлык "Code VM" и "ЗАПУСТИТЬ ВМ" на Рабочем столе
#   3. Автоматически создаёт модель drgr-visor (переученный qwen3-vl:8b)
#      с поддержкой ВИЗОРА, Monaco редактора и HTML-генератора
#   4. Открывает браузер с VM

$ErrorActionPreference = "SilentlyContinue"

$repoDir = if ($PSScriptRoot) {
    $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    (Get-Location).Path
}
Set-Location $repoDir

function Ok($msg)   { Write-Host "  [OK] $msg"    -ForegroundColor Green }
function Info($msg) { Write-Host "  [--] $msg"    -ForegroundColor Cyan }
function Warn($msg) { Write-Host "  [!!] $msg"    -ForegroundColor Yellow }
function Err($msg)  { Write-Host "  [ERR] $msg"   -ForegroundColor Red }

Write-Host ""
Write-Host "  =====================================================" -ForegroundColor White
Write-Host "   ЗАПУСТИТЬ ВМ — Code VM + Visor AI                  " -ForegroundColor White
Write-Host "   Переученная модель: drgr-visor (qwen3-vl:8b)       " -ForegroundColor Cyan
Write-Host "  =====================================================" -ForegroundColor White
Write-Host ""

# -- 1. Создать ярлык на рабочем столе ----------------------------------------
$desktopPath     = [Environment]::GetFolderPath("Desktop")
$createShortcut  = Join-Path $repoDir "vm\create_shortcut.ps1"
$psExe           = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path $psExe)) { $psExe = "powershell.exe" }

Info "Создаём ярлык 'Code VM' на рабочем столе..."
if (Test-Path $createShortcut) {
    try {
        $proc = Start-Process -FilePath $psExe `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$createShortcut`" -NoLaunch" `
            -WorkingDirectory $repoDir -Wait -PassThru -ErrorAction Stop
        if ($proc.ExitCode -eq 0) { Ok "Ярлык 'Code VM' создан на рабочем столе" }
    } catch { Warn "Не удалось создать ярлык через create_shortcut.ps1: $_" }
}

# Дополнительно: скопировать ЗАПУСТИТЬ_ВМ.bat на рабочий стол
$batSrc = Join-Path $repoDir 'ЗАПУСТИТЬ_ВМ.bat'
if (Test-Path $batSrc) {
    try {
        Copy-Item -Path $batSrc -Destination (Join-Path $desktopPath 'ЗАПУСТИТЬ_ВМ.bat') -Force
        Ok "Ярлык 'ЗАПУСТИТЬ_ВМ.bat' скопирован на рабочий стол"
    } catch { Warn "Не удалось скопировать ЗАПУСТИТЬ_ВМ.bat: $_" }
}

# Также скопировать ЗАПУСТИТЬ.bat как резервный лаунчер
$oldBat = Join-Path $repoDir 'ЗАПУСТИТЬ.bat'
if (Test-Path $oldBat) {
    try {
        Copy-Item -Path $oldBat -Destination (Join-Path $desktopPath 'ЗАПУСТИТЬ.bat') -Force
    } catch {}
}

# -- 2. Запустить VM ----------------------------------------------------------
$startPs1 = Join-Path $repoDir "start.ps1"
$vmPs1    = Join-Path $repoDir "vm.ps1"

Info "Запускаем Code VM..."
$vmStarted = $false
if (Test-Path $startPs1) {
    try {
        Start-Process -FilePath $psExe `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$startPs1`"" `
            -WorkingDirectory $repoDir
        $vmStarted = $true
        Ok "Code VM запускается... (порт 5000)"
    } catch { Warn "Не удалось запустить через start.ps1: $_" }
}
if (-not $vmStarted -and (Test-Path $vmPs1)) {
    try {
        Start-Process -FilePath $psExe `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$vmPs1`"" `
            -WorkingDirectory $repoDir
        Ok "Code VM запускается через vm.ps1..."
    } catch { Err "Не удалось запустить VM: $_" }
}

# -- 3. Подождать пока VM запустится, затем создать drgr-visor -----------------
Info "Ожидаем запуска VM (10 сек)..."
Start-Sleep -Seconds 10

$vmPort = if ($env:VM_PORT) { $env:VM_PORT } else { "5000" }
$vmUrl  = "http://127.0.0.1:$vmPort"

# Проверяем, запустилась ли VM
$vmReady = $false
for ($i = 0; $i -lt 6; $i++) {
    try {
        $hc = Invoke-WebRequest -Uri "$vmUrl/health" -TimeoutSec 3 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($hc.StatusCode -eq 200) { $vmReady = $true; break }
    } catch {}
    Start-Sleep -Seconds 3
}

if ($vmReady) {
    Ok "VM запущена! Открываем браузер..."

    # Открываем браузер
    try { Start-Process "$vmUrl" } catch {}

    # -- 4. Автоматически создаём переученную модель drgr-visor ---------------
    Info "Создаём переученную модель drgr-visor (qwen3-vl:8b + Monaco + ВИЗОР)..."
    Info "Это может занять несколько минут в зависимости от скорости Ollama."
    try {
        $createResp = Invoke-WebRequest -Uri "$vmUrl/ollama/create-visor-vm" `
            -Method POST -ContentType "application/json" -Body '{}' `
            -TimeoutSec 600 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($createResp -and $createResp.StatusCode -eq 200) {
            Ok "Модель drgr-visor создана успешно!"
            Ok "Теперь выбери 'drgr-visor' в настройках VM (☰ → Модель)"
        }
    } catch {
        Warn "Не удалось автоматически создать drgr-visor: $_"
        Warn "Создай вручную: нажми '🧠 Создать Visor VM' в левой панели VM"
    }
} else {
    Warn "VM не отвечает на $vmUrl"
    Warn "Проверь: запущена ли VM и не занят ли порт $vmPort"
    try { Start-Process "$vmUrl" } catch {}
}

Write-Host ""
Write-Host "  =====================================================" -ForegroundColor White
Write-Host "   VM запущена: $vmUrl                               " -ForegroundColor Cyan
Write-Host "   Переученная модель: drgr-visor (ВИЗОР + Monaco)   " -ForegroundColor Green
Write-Host "   Команды в Telegram: /visor, /browse, /code        " -ForegroundColor Cyan
Write-Host "  =====================================================" -ForegroundColor White
Write-Host ""
Write-Host "  Нажмите Enter для выхода..." -ForegroundColor DarkGray
Read-Host | Out-Null
