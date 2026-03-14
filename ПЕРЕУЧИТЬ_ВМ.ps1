# ПЕРЕУЧИТЬ_ВМ.ps1 — создать / обновить переученную модель drgr-visor
#
# Что делает скрипт:
#   1. Проверяет, запущена ли VM (Flask-сервер на порту 5000)
#   2. Если не запущена — запускает её в фоне
#   3. Вызывает POST /ollama/create-visor-vm и показывает прогресс
#
# Запуск: двойной клик по ПЕРЕУЧИТЬ_ВМ.bat или в PowerShell:
#   powershell -ExecutionPolicy Bypass -File ".\ПЕРЕУЧИТЬ_ВМ.ps1"

$ErrorActionPreference = "SilentlyContinue"

$repoDir = if ($PSScriptRoot) {
    $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    (Get-Location).Path
}
Set-Location $repoDir

function Ok($msg)   { Write-Host "  [OK] $msg"  -ForegroundColor Green }
function Info($msg) { Write-Host "  [--] $msg"  -ForegroundColor Cyan }
function Warn($msg) { Write-Host "  [!!] $msg"  -ForegroundColor Yellow }
function Err($msg)  { Write-Host "  [ERR] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "  =====================================================" -ForegroundColor White
Write-Host "   ПЕРЕУЧИТЬ ВМ — создать модель drgr-visor           " -ForegroundColor White
Write-Host "   Основана на qwen3-vl:8b + Monaco + ВИЗОР           " -ForegroundColor Cyan
Write-Host "  =====================================================" -ForegroundColor White
Write-Host ""

$psExe   = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path $psExe)) { $psExe = "powershell.exe" }
$vmPort  = if ($env:VM_PORT) { $env:VM_PORT } else { "5000" }
$vmUrl   = "http://127.0.0.1:$vmPort"

# -- 1. Проверяем, запущена ли VM -----------------------------------------------
Info "Проверяем VM ($vmUrl)..."
$vmReady = $false
try {
    $hc = Invoke-WebRequest -Uri "$vmUrl/health" -TimeoutSec 3 -UseBasicParsing -ErrorAction SilentlyContinue
    if ($hc -and $hc.StatusCode -eq 200) { $vmReady = $true }
} catch {}

if (-not $vmReady) {
    Info "VM не запущена — запускаем в фоне..."
    $startPs1 = Join-Path $repoDir "start.ps1"
    $vmPs1    = Join-Path $repoDir "vm.ps1"
    if (Test-Path $startPs1) {
        Start-Process -FilePath $psExe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$startPs1`"" -WorkingDirectory $repoDir
    } elseif (Test-Path $vmPs1) {
        Start-Process -FilePath $psExe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$vmPs1`"" -WorkingDirectory $repoDir
    } else {
        Err "Не найден start.ps1 / vm.ps1 в $repoDir"
        Write-Host ""
        Read-Host "  Нажмите Enter для выхода"
        exit 1
    }

    Info "Ожидаем запуска VM (до 30 сек)..."
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Seconds 3
        try {
            $hc = Invoke-WebRequest -Uri "$vmUrl/health" -TimeoutSec 3 -UseBasicParsing -ErrorAction SilentlyContinue
            if ($hc -and $hc.StatusCode -eq 200) { $vmReady = $true; break }
        } catch {}
    }
}

if (-not $vmReady) {
    Warn "VM не отвечает на $vmUrl"
    Warn "Попробуем переучить через 5 сек (может занять дольше)..."
    Start-Sleep -Seconds 5
}

Ok "VM запущена. Начинаем создание переученной модели drgr-visor..."
Write-Host ""

# -- 2. Вызываем POST /ollama/create-visor-vm с потоковым выводом ---------------
Info "Создаём drgr-visor (qwen3-vl:8b + системный промпт ВИЗОРА)..."
Info "Это может занять 1–5 минут. Не закрывай окно!"
Write-Host ""

$success = $false
try {
    Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue
    $client  = New-Object System.Net.Http.HttpClient
    $client.Timeout = [TimeSpan]::FromMinutes(30)
    $content = New-Object System.Net.Http.StringContent '{}', ([System.Text.Encoding]::UTF8), 'application/json'
    $task    = $client.PostAsync("$vmUrl/ollama/create-visor-vm", $content)
    $resp    = $task.GetAwaiter().GetResult()
    $stream  = $resp.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
    $reader  = New-Object System.IO.StreamReader $stream

    while (-not $reader.EndOfStream) {
        $line = $reader.ReadLine()
        if (-not $line) { continue }
        if (-not $line.StartsWith("data: ")) { continue }
        $json = $line.Substring(6)
        try {
            $obj = $json | ConvertFrom-Json
            if ($obj.error) {
                Err "Ошибка Ollama: $($obj.error)"
                break
            }
            if ($obj.status) {
                Write-Host "    $($obj.status)" -ForegroundColor DarkGray
            }
            if ($obj.done -eq $true) {
                $success = $true
            }
        } catch { }
    }
    $reader.Close()
    $client.Dispose()
} catch {
    Warn "Ошибка HTTP-клиента: $_"
    Warn "Пробуем через Invoke-WebRequest (без потокового вывода)..."
    try {
        $wr = Invoke-WebRequest -Uri "$vmUrl/ollama/create-visor-vm" `
            -Method POST -ContentType "application/json" -Body '{}' `
            -TimeoutSec 600 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($wr -and $wr.StatusCode -eq 200) { $success = $true }
    } catch {
        Err "Не удалось вызвать /ollama/create-visor-vm: $_"
    }
}

Write-Host ""
if ($success) {
    Write-Host "  =====================================================" -ForegroundColor Green
    Write-Host "   ✅ Переученная ВМ готова!                          " -ForegroundColor Green
    Write-Host "   Модель: drgr-visor (qwen3-vl:8b + ВИЗОР + Monaco) " -ForegroundColor Green
    Write-Host "  =====================================================" -ForegroundColor Green
    Write-Host ""
    Ok "Открываем браузер на переученной ВМ..."
    try { Start-Process "$vmUrl" } catch {}
    Write-Host ""
    Write-Host "  Как использовать:" -ForegroundColor White
    Write-Host "    1. Открой $vmUrl в браузере" -ForegroundColor Cyan
    Write-Host "    2. Нажми ☰ → выбери модель 'drgr-visor'" -ForegroundColor Cyan
    Write-Host "    3. Нажми вкладку '💬 Чат' или '🧠 Переученная ВМ'" -ForegroundColor Cyan
} else {
    Write-Host "  =====================================================" -ForegroundColor Yellow
    Write-Host "   ⚠ Создание не подтверждено                        " -ForegroundColor Yellow
    Write-Host "  =====================================================" -ForegroundColor Yellow
    Write-Host ""
    Warn "Возможно Ollama не запущена или модель qwen3-vl:8b не скачана."
    Write-Host ""
    Write-Host "  Проверь:" -ForegroundColor White
    Write-Host "    1. Запущена ли Ollama:     ollama serve" -ForegroundColor Cyan
    Write-Host "    2. Есть ли базовая модель: ollama list" -ForegroundColor Cyan
    Write-Host "    3. Скачай если нет:        ollama pull qwen3-vl:8b" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Или нажми '🧠 Переученная ВМ' прямо в браузере: $vmUrl" -ForegroundColor Cyan
    try { Start-Process "$vmUrl" } catch {}
}

Write-Host ""
Write-Host "  Нажмите Enter для выхода..." -ForegroundColor DarkGray
Read-Host | Out-Null
