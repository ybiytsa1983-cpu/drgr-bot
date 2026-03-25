<#
.SYNOPSIS
    Запуск DRGR вместе с LM Studio и Ollama.

.DESCRIPTION
    1. Запускает LM Studio (порт 1234) — если найден exe
    2. Проверяет / запускает Ollama (порт 11434)
    3. Сохраняет LM_STUDIO_URL в .env
    4. Запускает VM-сервер и Telegram-бот (через ЗАПУСТИТЬ_ВСЕ.ps1)

.PARAMETER Token
    Telegram Bot Token (необязательно).

.PARAMETER LmStudioExe
    Путь к LM Studio exe. Если не указан — пытается найти автоматически.

.PARAMETER LmStudioPort
    Порт LM Studio (по умолчанию 1234).
#>
param(
    [string]$Token       = "",
    [string]$LmStudioExe = "",
    [int]   $LmStudioPort = 1234
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
Say "  |   DRGR — Запуск с LM Studio + Ollama + VM         |" "Cyan"
Say "  +====================================================+" "Cyan"
Say ""

# ── Step 1: Find LM Studio ────────────────────────────────────────────────────
Say "► Шаг 1: LM Studio"

$lmsExe = $LmStudioExe
if (-not $lmsExe) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\LM Studio\LM Studio.exe",
        "$env:PROGRAMFILES\LM Studio\LM Studio.exe",
        "${env:PROGRAMFILES(X86)}\LM Studio\LM Studio.exe",
        "$env:USERPROFILE\AppData\Local\Programs\LM Studio\LM Studio.exe",
        "C:\Program Files\LM Studio\LM Studio.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $lmsExe = $c; break }
    }
}

$lmsProc   = $null
$lmsUrl    = "http://localhost:$LmStudioPort"
$lmsRunning = $false

# Check if LM Studio is already listening on the port
try {
    $probe = Invoke-WebRequest -Uri "$lmsUrl/v1/models" -TimeoutSec 2 -UseBasicParsing -EA Stop
    if ($probe.StatusCode -lt 400) { $lmsRunning = $true; Ok "LM Studio уже запущена на порту $LmStudioPort" }
} catch {}

if (-not $lmsRunning) {
    if ($lmsExe -and (Test-Path $lmsExe)) {
        Say "  Запускаю LM Studio: $lmsExe" "Yellow"
        # LM Studio needs to be started with --server-port flag or the user starts the server manually.
        # We launch the GUI and wait for the API to come up.
        $lmsProc = Start-Process -FilePath $lmsExe -PassThru -WindowStyle Minimized -EA SilentlyContinue
        if ($lmsProc) { Ok "LM Studio запускается (PID $($lmsProc.Id))..." }

        Info "Жду появления LM Studio API (до 30 сек)..."
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep 1
            try {
                $probe = Invoke-WebRequest -Uri "$lmsUrl/v1/models" -TimeoutSec 1 -UseBasicParsing -EA Stop
                if ($probe.StatusCode -lt 400) { $lmsRunning = $true; Ok "LM Studio API готова!"; break }
            } catch {}
        }
        if (-not $lmsRunning) {
            Info "LM Studio API пока недоступна — возможно, нужно вручную запустить сервер в GUI."
            Info "После запуска LM Studio сервера откройте настройки VM (⚙) и сохраните URL: $lmsUrl"
        }
    } else {
        Info "LM Studio exe не найден."
        Info "Укажите путь параметром: -LmStudioExe 'C:\...\LM Studio.exe'"
        Info "Или запустите LM Studio вручную и в настройках VM укажите URL: $lmsUrl"
    }
}

# ── Step 2: Check Ollama ──────────────────────────────────────────────────────
Say ""
Say "► Шаг 2: Ollama"

$ollamaOk = $false
try {
    $olProbe = Invoke-WebRequest -Uri "http://localhost:11434" -TimeoutSec 2 -UseBasicParsing -EA Stop
    if ($olProbe.StatusCode -lt 400) { $ollamaOk = $true; Ok "Ollama работает" }
} catch {}

if (-not $ollamaOk) {
    $ollamaExe = $null
    $olCandidates = @(
        "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
        "$env:USERPROFILE\AppData\Local\Programs\Ollama\ollama.exe",
        "C:\Program Files\Ollama\ollama.exe",
        "ollama"
    )
    foreach ($c in $olCandidates) {
        try { if (Get-Command $c -EA SilentlyContinue) { $ollamaExe = $c; break } } catch {}
        if ($c -ne "ollama" -and (Test-Path $c)) { $ollamaExe = $c; break }
    }
    if ($ollamaExe) {
        Say "  Запускаю Ollama..." "Yellow"
        Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden -EA SilentlyContinue
        Start-Sleep 3
        try {
            $probe = Invoke-WebRequest -Uri "http://localhost:11434" -TimeoutSec 2 -UseBasicParsing -EA Stop
            if ($probe.StatusCode -lt 400) { $ollamaOk = $true; Ok "Ollama запущена" }
        } catch { Info "Ollama не ответила — продолжаю без неё." }
    } else {
        Info "Ollama не найдена — будет использован LM Studio (если настроен)."
    }
}

# ── Step 3: Update .env with LM_STUDIO_URL ───────────────────────────────────
Say ""
Say "► Шаг 3: Сохраняю LM_STUDIO_URL в .env"

$envFile = Join-Path $repoDir ".env"
$lmsLine = "LM_STUDIO_URL=$lmsUrl"

if (Test-Path $envFile) {
    $lines = Get-Content $envFile
    $found = $false
    $newLines = $lines | ForEach-Object {
        if ($_ -match "^LM_STUDIO_URL=") { $found = $true; $lmsLine } else { $_ }
    }
    if (-not $found) { $newLines += $lmsLine }
    $newLines | Set-Content $envFile -Encoding UTF8
} else {
    $lmsLine | Set-Content $envFile -Encoding UTF8
}
Ok "LM_STUDIO_URL=$lmsUrl записан в .env"

# ── Step 4: Launch main startup (VM + Bot + Browser) ─────────────────────────
Say ""
Say "► Шаг 4: Запускаю основной сценарий ЗАПУСТИТЬ_ВСЕ.ps1"
Say ""

$mainScript = Join-Path $repoDir "ЗАПУСТИТЬ_ВСЕ.ps1"
if (Test-Path $mainScript) {
    if ($Token) {
        & $mainScript -Token $Token
    } else {
        & $mainScript
    }
} else {
    Err "ЗАПУСТИТЬ_ВСЕ.ps1 не найден в $repoDir"
}
