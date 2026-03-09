<#
.SYNOPSIS
    ONE-COMMAND launcher for Code VM.

.DESCRIPTION
    Run this script ONCE — it installs everything on first launch, then opens
    the editor.  On every subsequent run it just opens the editor immediately.

    Usage in PowerShell (always include .\):
        .\start.ps1

    If you see "running scripts is disabled", run this ONCE first, then retry:
        Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

.NOTES
    You can also double-click start.bat in Windows Explorer (no .\  needed there).
#>

# ── Resolve the directory containing this script ──────────────────────────────
# $PSScriptRoot is empty when PS is started without -File (e.g. some shortcuts
# or "powershell start.ps1" instead of "powershell -File start.ps1").
# Fall back to $MyInvocation, then to the current working directory.
$scriptRoot = if ($PSScriptRoot) {
    $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    (Get-Location).Path
}

# ── Always run from the repository root ───────────────────────────────────────
Set-Location $scriptRoot

# ── Auto-update from remote (silent, best-effort) ────────────────────────────
try { git pull --ff-only --quiet 2>$null } catch { }

# ── First-time setup if .venv is missing ──────────────────────────────────────
$venvPython = Join-Path $scriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host ""
    Write-Host "  ╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "  ║  Code VM — первый запуск, выполняется установка...   ║" -ForegroundColor Cyan
    Write-Host "  ║  Подождите ~1-2 минуты.                              ║" -ForegroundColor Cyan
    Write-Host "  ╚═══════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""

    # ── Find Python ───────────────────────────────────────────────────────────
    $python = $null
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $ver = & $cmd --version 2>&1
            if ($ver -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 8) {
                $python = $cmd
                Write-Host "  [OK] Python найден: $ver" -ForegroundColor Green
                break
            }
        } catch { }
    }

    if (-not $python) {
        Write-Host ""
        Write-Host "  [ОШИБКА] Python 3.8+ не найден." -ForegroundColor Red
        Write-Host ""
        Write-Host "  Установите Python с сайта:" -ForegroundColor Yellow
        Write-Host "    https://www.python.org/downloads/" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  ВАЖНО: при установке поставьте галочку 'Add Python to PATH'" -ForegroundColor Yellow
        Write-Host ""
        Read-Host "  Нажмите Enter для выхода"
        exit 1
    }

    # ── Create .venv ──────────────────────────────────────────────────────────
    Write-Host "  [--] Создание виртуального окружения..." -ForegroundColor Cyan
    & $python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ОШИБКА] Не удалось создать .venv." -ForegroundColor Red
        Read-Host "  Нажмите Enter для выхода"
        exit 1
    }

    # ── Install dependencies ──────────────────────────────────────────────────
    Write-Host "  [--] Установка зависимостей (flask, requests)..." -ForegroundColor Cyan
    & ".venv\Scripts\pip" install flask requests --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ОШИБКА] Не удалось установить пакеты." -ForegroundColor Red
        Read-Host "  Нажмите Enter для выхода"
        exit 1
    }

    # ── Optional full requirements.txt ───────────────────────────────────────
    if (Test-Path "requirements.txt") {
        Write-Host "  [--] Установка requirements.txt..." -ForegroundColor Cyan
        & ".venv\Scripts\pip" install -r requirements.txt --quiet 2>$null
    }

    # ── Create Desktop shortcut (so user has icon next time) ─────────────────
    try {
        $desktopPath  = [Environment]::GetFolderPath("Desktop")
        $shortcutPath = Join-Path $desktopPath "Code VM.lnk"
        $batTarget    = Join-Path $scriptRoot "start.bat"
        $shell        = New-Object -ComObject WScript.Shell
        $shortcut     = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath       = $batTarget
        $shortcut.WorkingDirectory = $scriptRoot
        $shortcut.Description      = "Launch Code VM - Monaco Editor with Ollama AI"
        $shortcut.WindowStyle      = 1
        $pyCmd = Get-Command python  -ErrorAction SilentlyContinue
        if (-not $pyCmd) { $pyCmd = Get-Command python3 -ErrorAction SilentlyContinue }
        if (-not $pyCmd) { $pyCmd = Get-Command py      -ErrorAction SilentlyContinue }
        if ($pyCmd) { $shortcut.IconLocation = "$($pyCmd.Source),0" }
        else        { $shortcut.IconLocation = "%SystemRoot%\System32\cmd.exe,0" }
        $shortcut.Save()
        Write-Host "  [OK] Ярлык 'Code VM' создан на Рабочем столе" -ForegroundColor Green
    } catch {
        # Non-fatal — icon is nice but not required
        Write-Host "  [!] Ярлык не создан (не критично): $_" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "  [OK] Установка завершена!" -ForegroundColor Green
    Write-Host ""
}

# ── Launch the VM server in a new visible window ──────────────────────────────
$vmBat = Join-Path $scriptRoot "vm\start_vm.bat"
Write-Host "  [-->] Запуск Code VM..." -ForegroundColor Cyan
Start-Process -FilePath "cmd.exe" -ArgumentList "/k `"$vmBat`"" -WorkingDirectory $scriptRoot
Write-Host "  [OK] Code VM запускается — браузер откроется через несколько секунд." -ForegroundColor Green
Write-Host "       Закройте окно 'Code VM - Monaco Editor' чтобы остановить сервер." -ForegroundColor Yellow
Write-Host ""
