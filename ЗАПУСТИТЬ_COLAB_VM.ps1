<#
.SYNOPSIS
    Авто-запуск Colab VM в расширении DRGR.

.DESCRIPTION
    1. Запускает VM-сервер (через ЗАПУСТИТЬ_ВСЕ.ps1 если ещё не запущен)
    2. Отправляет /colab/autostart запрос с указанным Colab URL
    3. Открывает браузер на панели Colab VM

.PARAMETER ColabUrl
    URL Google Colab VM (через ngrok/cloudflare tunnel).
    Пример: https://xxxx.ngrok-free.app

.PARAMETER Token
    Telegram Bot Token (необязательно).

.PARAMETER VmPort
    Порт VM-сервера (по умолчанию 8080).
#>
param(
    [string]$ColabUrl = "",
    [string]$Token    = "",
    [int]   $VmPort   = 8080
)

$ErrorActionPreference = "Continue"

$repoDir = if ($PSScriptRoot) { $PSScriptRoot }
           elseif ($MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path }
           else { (Get-Location).Path }
Set-Location $repoDir

function Say($msg, $color = "Cyan") { Write-Host $msg -ForegroundColor $color }
function Err($msg) { Write-Host "  [!] $msg" -ForegroundColor Red }
function Ok($msg)  { Write-Host "  [+] $msg" -ForegroundColor Green }
function Info($msg){ Write-Host "  [~] $msg" -ForegroundColor Yellow }

Say ""
Say "  +====================================================+" "Cyan"
Say "  |   DRGR — Авто-запуск Colab VM в расширении        |" "Cyan"
Say "  +====================================================+" "Cyan"
Say ""

# ── Step 1: Ask for Colab URL if not provided ────────────────────────────────
if (-not $ColabUrl) {
    $ColabUrl = Read-Host "Введите URL Colab VM (например: https://xxxx.ngrok-free.app)"
    $ColabUrl = $ColabUrl.Trim().TrimEnd("/")
}

if (-not $ColabUrl) {
    Err "URL не указан. Выход."
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

if (-not ($ColabUrl -match "^https?://")) {
    Err "URL должен начинаться с http:// или https://"
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

Say "► Шаг 1: Проверяю, запущен ли VM-сервер..."
$vmUrl   = "http://localhost:$VmPort"
$vmAlive = $false

try {
    $probe = Invoke-WebRequest -Uri "$vmUrl/health" -TimeoutSec 3 -UseBasicParsing -EA Stop
    if ($probe.StatusCode -lt 400) {
        $vmAlive = $true
        Ok "VM-сервер уже запущен на порту $VmPort"
    }
} catch {}

if (-not $vmAlive) {
    Say "► VM-сервер не запущен. Запускаю..."
    $startAll = Join-Path $repoDir "ЗАПУСТИТЬ_ВСЕ.ps1"
    if (Test-Path $startAll) {
        if ($Token) {
            Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$startAll`" -Token `"$Token`"" -WindowStyle Normal
        } else {
            Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$startAll`"" -WindowStyle Normal
        }
        Info "Жду запуска VM-сервера (до 20 сек)..."
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep 1
            try {
                $probe = Invoke-WebRequest -Uri "$vmUrl/health" -TimeoutSec 2 -UseBasicParsing -EA Stop
                if ($probe.StatusCode -lt 400) { $vmAlive = $true; Ok "VM-сервер запущен"; break }
            } catch {}
        }
    } else {
        Info "Файл ЗАПУСТИТЬ_ВСЕ.ps1 не найден. Убедитесь что VM-сервер запущен вручную."
    }
}

if (-not $vmAlive) {
    Err "VM-сервер не отвечает на $vmUrl. Запустите его вручную и повторите."
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

# ── Step 2: Send autostart request ──────────────────────────────────────────
Say "► Шаг 2: Отправляю Colab URL в VM ($ColabUrl)..."

try {
    $body = '{"url":"' + $ColabUrl + '"}'
    $resp = Invoke-WebRequest -Uri "$vmUrl/colab/autostart" -Method POST `
        -ContentType "application/json" -Body $body -TimeoutSec 10 -UseBasicParsing -EA Stop

    $json = $resp.Content | ConvertFrom-Json
    if ($json.ok) {
        Ok "Colab VM настроен: $ColabUrl"
        if ($json.connected) { Ok "Соединение с Colab VM активно" }
        else { Info "Colab VM недоступен (возможно, ещё не запущен в Colab). URL сохранён." }
    } else {
        Err "Ошибка автозапуска: $($json.error)"
    }
} catch {
    Err "Ошибка при отправке запроса: $_"
}

# ── Step 3: Open browser ──────────────────────────────────────────────────────
Say "► Шаг 3: Открываю браузер на панели Colab VM..."

$uiUrl = "$vmUrl/?view=colab"
if ($ColabUrl) {
    $uiUrl = "$vmUrl/?view=colab&colab_url=" + [Uri]::EscapeDataString($ColabUrl)
}

try {
    Start-Process $uiUrl
    Ok "Браузер открыт: $uiUrl"
} catch {
    Info "Открой браузер вручную: $uiUrl"
}

Say ""
Say "  ✅ Colab VM интегрирован в расширение DRGR!" "Green"
Say "  URL: $ColabUrl" "Green"
Say "  VM:  $vmUrl" "Green"
Say ""

Read-Host "Нажмите Enter для завершения"
