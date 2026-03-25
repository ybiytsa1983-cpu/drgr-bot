# DRGR Auto-Start - Полный автозапуск системы
# Запускает: Ollama, VM-сервер, Telegram-бот, LM Studio

param([string]$Token = "")

$ErrorActionPreference = "Continue"
$repoDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
Set-Location $repoDir

function Say($msg) { Write-Host " [*] $msg" -ForegroundColor Cyan }
function Err($msg) { Write-Host " [!] $msg" -ForegroundColor Red }
function Ok($msg) { Write-Host " [+] $msg" -ForegroundColor Green }

Say "DRGR AUTO-START - Запуск всех сервисов"
Say "="*60

# === 1. Проверка Python venv ===
Say "Проверка Python..."
$venvPython = Join-Path $repoDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Err ".venv не найден! Запустите install.bat сначала"
    pause; exit 1
}
Ok "Python venv готов"

# === 2. Запуск Ollama ===
Say "Запуск Ollama..."
$ollamaRunning = $false
foreach ($port in 11434..11445) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$port/api/tags" -TimeoutSec 1 -UseBasicParsing -EA Stop
        Ok "Ollama уже запущена на порту $port"
        $env:OLLAMA_HOST = "http://localhost:$port"
        $ollamaRunning = $true
        break
    } catch {}
}

if (-not $ollamaRunning) {
    if (Get-Command ollama -EA SilentlyContinue) {
        Say "Запуск ollama serve..."
        Start-Process -FilePath "ollama" -ArgumentList "serve" -NoNewWindow -PassThru | Out-Null
        Start-Sleep 3
        Ok "Ollama запущена"
    } else {
        Err "Ollama не установлена. Скачайте: https://ollama.ai"
    }
}

# === 3. Запуск LM Studio (если установлен) ===
Say "Проверка LM Studio..."
$lmStudioPath = "$env:LOCALAPPDATA\LM Studio\lms.exe"
if (Test-Path $lmStudioPath) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:1234/v1/models" -TimeoutSec 1 -UseBasicParsing -EA Stop
        Ok "LM Studio уже запущен"
    } catch {
        Say "Запуск LM Studio..."
        Start-Process -FilePath $lmStudioPath -NoNewWindow -PassThru | Out-Null
        Ok "LM Studio запущен"
    }
} else {
    Say "LM Studio не найден (опционально)"
}

# === 4. Запуск VM-сервера ===
Say "Запуск VM-сервера..."
$old = Get-NetTCPConnection -LocalPort 5000 -State Listen -EA SilentlyContinue
if ($old) {
    $old | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -EA SilentlyContinue }
    Start-Sleep 1
}

$vmLog = Join-Path $repoDir "vm_server.log"
$vmProc = Start-Process -FilePath $venvPython `
    -ArgumentList (Join-Path $repoDir "vm\server.py") `
    -WorkingDirectory (Join-Path $repoDir "vm") `
    -RedirectStandardOutput $vmLog `
    -RedirectStandardError $vmLog `
    -NoNewWindow -PassThru

Start-Sleep 3
try {
    Invoke-WebRequest -Uri "http://localhost:5000/health" -TimeoutSec 2 -UseBasicParsing -EA Stop | Out-Null
    Ok "VM-сервер запущен (PID $($vmProc.Id))"
} catch {
    Err "VM-сервер не отвечает. См. лог: $vmLog"
}

# === 5. Запуск Telegram-бота ===
if (-not $Token) { $Token = $env:BOT_TOKEN }
if ($Token) {
    Say "Запуск Telegram-бота..."
    $botLog = Join-Path $repoDir "bot.log"
    $botProc = Start-Process -FilePath $venvPython `
        -ArgumentList (Join-Path $repoDir "bot.py") `
        -WorkingDirectory $repoDir `
        -RedirectStandardOutput $botLog `
        -RedirectStandardError $botLog `
        -NoNewWindow -PassThru
    Start-Sleep 2
    if (-not $botProc.HasExited) {
        Ok "Telegram-бот запущен (PID $($botProc.Id))"
    }
} else {
    Say "BOT_TOKEN не задан - бот не запущен"
}

# === 6. Открытие браузера ===
Say "Открытие браузера..."
Start-Process "http://localhost:5000"
Ok "Браузер открыт"

# === Статус ===
Say "="*60
Ok "Система запущена!"
Say "VM-интерфейс: http://localhost:5000"
Say "Нажмите Enter для остановки..."
Read-Host | Out-Null

# === Остановка ===
Say "Остановка..."
if ($vmProc -and -not $vmProc.HasExited) { Stop-Process -Id $vmProc.Id -Force -EA SilentlyContinue }
if ($botProc -and -not $botProc.HasExited) { Stop-Process -Id $botProc.Id -Force -EA SilentlyContinue }
Ok "Готово"
