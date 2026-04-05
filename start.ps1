# start.ps1 — DRGR Bot полный лаунчер
# Автоопределение Ollama, проверка портов, установка зависимостей, запуск сервера
param(
    [int]$Port = 5001,
    [switch]$NoBrowser,
    [switch]$NoOllama
)

$ErrorActionPreference = "Continue"
$Host.UI.RawUI.WindowTitle = "DRGR VM Server"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  DRGR VM Server — Launcher" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# --- cd в директорию скрипта ---
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
Write-Host "[start] Рабочая папка: $ScriptDir" -ForegroundColor DarkGray

# --- Проверка Python ---
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python\s+3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 10) {
                $pythonCmd = $cmd
                Write-Host "[start] Python: $ver" -ForegroundColor Green
                break
            }
        }
    } catch {}
}
if (-not $pythonCmd) {
    Write-Host "[start] ОШИБКА: Python 3.10+ не найден!" -ForegroundColor Red
    Write-Host "  Установите: https://www.python.org/downloads/" -ForegroundColor Yellow
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

# --- Проверка/установка зависимостей ---
Write-Host ""
Write-Host "[start] Установка/обновление зависимостей..." -ForegroundColor Yellow
& $pythonCmd -m pip install --upgrade pip --quiet 2>$null
& $pythonCmd -m pip install -r requirements.txt --quiet 2>&1 | ForEach-Object {
    if ($_ -match "ERROR|error") { Write-Host "  $_" -ForegroundColor Red }
}
Write-Host "[start] Зависимости установлены" -ForegroundColor Green

# --- Ollama ---
if (-not $NoOllama) {
    Write-Host ""
    Write-Host "[start] Проверка Ollama..." -ForegroundColor Yellow
    
    $ollamaRunning = $false
    $ollamaPorts = @(11434, 11435, 11436, 11437)
    foreach ($p in $ollamaPorts) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$p/api/tags" -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -lt 500) {
                Write-Host "[start] Ollama обнаружена на порту $p" -ForegroundColor Green
                $ollamaRunning = $true
                $env:OLLAMA_HOST = "127.0.0.1:$p"
                break
            }
        } catch {}
    }
    
    if (-not $ollamaRunning) {
        # Попытка запустить Ollama
        $ollamaPath = Get-Command ollama -ErrorAction SilentlyContinue
        if ($ollamaPath) {
            Write-Host "[start] Запуск Ollama..." -ForegroundColor Yellow
            Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
            Start-Sleep -Seconds 3
            try {
                $resp = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 -ErrorAction Stop
                Write-Host "[start] Ollama запущена на порту 11434" -ForegroundColor Green
                $ollamaRunning = $true
            } catch {
                Write-Host "[start] Ollama не смогла запуститься" -ForegroundColor Yellow
            }
        } else {
            Write-Host "[start] Ollama не установлена (https://ollama.com)" -ForegroundColor Yellow
            Write-Host "[start] Чат и генератор статей будут недоступны без LLM" -ForegroundColor Yellow
        }
    }
    
    # Проверка LM Studio
    $lmStudioPorts = @(1234, 1235)
    foreach ($p in $lmStudioPorts) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$p/v1/models" -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -lt 500) {
                Write-Host "[start] LM Studio обнаружена на порту $p" -ForegroundColor Green
                break
            }
        } catch {}
    }
}

# --- Проверка порта ---
Write-Host ""
$portInUse = $false
try {
    $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($conn) {
        $portInUse = $true
        $pid = $conn[0].OwningProcess
        $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
        Write-Host "[start] ВНИМАНИЕ: Порт $Port уже занят процессом $($proc.Name) (PID $pid)" -ForegroundColor Red
        Write-Host "[start] Попытка остановки..." -ForegroundColor Yellow
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        $conn2 = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
        if ($conn2) {
            Write-Host "[start] Не удалось освободить порт $Port. Попробуйте вручную:" -ForegroundColor Red
            Write-Host "  netstat -ano | findstr :$Port" -ForegroundColor Yellow
            Read-Host "Нажмите Enter для выхода"
            exit 1
        }
        Write-Host "[start] Порт $Port освобождён" -ForegroundColor Green
    }
} catch {}

# --- Проверка .env ---
if (Test-Path ".env") {
    Write-Host "[start] .env файл найден" -ForegroundColor Green
} else {
    Write-Host "[start] .env не найден — бот не будет автозапущен" -ForegroundColor Yellow
    Write-Host "[start] Создайте .env с BOT_TOKEN через веб-интерфейс (Настройки)" -ForegroundColor Yellow
}

# --- Запуск ---
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Запуск VM сервера на http://localhost:$Port" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Веб-интерфейс: http://localhost:$Port" -ForegroundColor Cyan
Write-Host "  Чат с AI, генератор статей, управление ботом" -ForegroundColor Cyan
Write-Host "  Ctrl+C — остановка" -ForegroundColor DarkGray
Write-Host ""

# Открыть браузер
if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        Start-Sleep -Seconds 3
        Start-Process "http://localhost:$using:Port"
    } | Out-Null
}

# Запуск сервера
& $pythonCmd vm/server.py
