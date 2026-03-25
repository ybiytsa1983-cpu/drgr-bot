#Requires -Version 5.1
<#
.SYNOPSIS
    Установка браузерного расширения DRGR Bot.
.DESCRIPTION
    Генерирует PNG-иконки и открывает страницу расширений браузера,
    чтобы пользователь мог загрузить папку extension/ как "распакованное расширение".

    Запуск:
        Set-ExecutionPolicy -Scope Process Bypass
        .\УСТАНОВИТЬ_РАСШИРЕНИЕ.ps1
#>

$ErrorActionPreference = 'Continue'

$BotDir = $PSScriptRoot
$ExtDir = Join-Path $BotDir 'extension'

function Write-Step([string]$msg) { Write-Host "`n[EXT] $msg" -ForegroundColor Cyan }
function Write-OK([string]$msg)   { Write-Host "  OK  $msg"   -ForegroundColor Green  }
function Write-Warn([string]$msg) { Write-Host "  WARN  $msg" -ForegroundColor Yellow }
function Write-Err([string]$msg)  { Write-Host "  ERR  $msg"  -ForegroundColor Red    }

try {

Write-Host ""
Write-Host "+------------------------------------------------+" -ForegroundColor Magenta
Write-Host "|   DRGR Bot  |  Браузерное расширение           |" -ForegroundColor Magenta
Write-Host "+------------------------------------------------+" -ForegroundColor Magenta

# ── 1. Генерация иконок ───────────────────────────────────────────────────
Write-Step "[1/3] Генерация PNG-иконок..."

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Warn "Python не найден — иконки пропускаются."
} else {
    $result = python "$ExtDir\make_icons.py" 2>&1
    if ($LASTEXITCODE -eq 0) {
        $result | ForEach-Object { Write-Host "  $_" }
        Write-OK "Иконки созданы."
    } else {
        Write-Warn "Не удалось создать иконки: $result"
        Write-Warn "Запустите вручную: pip install pillow && python $ExtDir\make_icons.py"
    }
}

# ── 2. Инструкция ─────────────────────────────────────────────────────────
Write-Step "[2/3] Инструкция по установке расширения"
Write-Host ""
Write-Host "  Как установить расширение в браузер (один раз):" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Chrome  →  chrome://extensions"  -ForegroundColor Gray
Write-Host "  Edge    →  edge://extensions"    -ForegroundColor Gray
Write-Host "  Brave   →  brave://extensions"   -ForegroundColor Gray
Write-Host ""
Write-Host "  1. Включите «Режим разработчика» (переключатель вверху справа)" -ForegroundColor White
Write-Host "  2. Нажмите «Загрузить распакованное»" -ForegroundColor White
Write-Host "  3. Укажите папку:" -ForegroundColor White
Write-Host "     $ExtDir" -ForegroundColor Cyan
Write-Host "  4. Значок D появится на панели браузера!" -ForegroundColor White
Write-Host ""

# ── 3. Автооткрытие браузера ──────────────────────────────────────────────
Write-Step "[3/3] Открытие страницы расширений..."

$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
)
$edgePath = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"

$launched = $false
foreach ($p in $chromePaths) {
    if (Test-Path $p) {
        Write-OK "Открываем Chrome: chrome://extensions"
        Start-Process $p "chrome://extensions"
        $launched = $true
        break
    }
}

if (-not $launched -and (Test-Path $edgePath)) {
    Write-OK "Chrome не найден. Открываем Edge: edge://extensions"
    Start-Process $edgePath "edge://extensions"
    $launched = $true
}

if (-not $launched) {
    Write-Warn "Браузер не найден. Откройте его вручную и перейдите на chrome://extensions"
}

# ── Итог ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "+------------------------------------------------+" -ForegroundColor Green
Write-Host "|  Папка расширения готова к установке!          |" -ForegroundColor Green
Write-Host "+------------------------------------------------+" -ForegroundColor Green
Write-Host "  Путь: $ExtDir" -ForegroundColor Cyan
Write-Host ""
Write-Host "  После установки кликните значок D в панели браузера." -ForegroundColor White
Write-Host "  Расширение откроет веб-интерфейс DRGR Bot на localhost:5001." -ForegroundColor White
Write-Host ""

} finally {
    Read-Host "  Нажмите Enter для закрытия"
}
