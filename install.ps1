<#
.SYNOPSIS
    Первоначальная установка Code VM на Windows (PowerShell).

.DESCRIPTION
    Запусти один раз после клонирования репозитория:
        .\install.ps1

    Что делает скрипт:
      1. Проверяет наличие Python 3.8+
      2. Создаёт виртуальное окружение (.venv)
      3. Устанавливает зависимости Python (Flask, requests)
      4. Скачивает Monaco Editor локально (после этого работает без интернета)
      5. Автоматически скачивает и устанавливает Ollama
      6. Запускает загрузку AI-модели в фоне
      7. Создаёт ярлык «Code VM» на Рабочем столе

.NOTES
    Если видишь «script cannot be loaded because running scripts is disabled»,
    выполни один раз чтобы разрешить локальные скрипты:
        Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
    Затем повтори: .\install.ps1
#>

$ErrorActionPreference = "Stop"

# $PSScriptRoot is empty when PS is invoked without -File (e.g. some shortcuts
# or "powershell install.ps1" instead of "powershell -File install.ps1").
# Fall back to $MyInvocation, then to the current working directory.
$repoDir = if ($PSScriptRoot) {
    $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    (Get-Location).Path
}
Set-Location $repoDir

# -- 0. Auto-update repo -------------------------------------------------------
# If this is a git repo, pull latest changes so old installs get fixes.
# If install.ps1 itself changed, re-exec the new version immediately so the
# user doesn't have to run the script twice to benefit from the latest fixes.
$selfPath = Join-Path $repoDir "install.ps1"
if (Test-Path (Join-Path $repoDir ".git")) {
    $hashBefore = if (Test-Path $selfPath) { (Get-FileHash $selfPath -Algorithm MD5).Hash } else { "" }
    try {
        $gitLines = & git pull 2>&1
        foreach ($line in $gitLines) {
            Write-Host "  [GIT] $line" -ForegroundColor DarkGray
        }
    } catch { }
    if ($hashBefore -ne "" -and (Test-Path $selfPath)) {
        $hashAfter = (Get-FileHash $selfPath -Algorithm MD5).Hash
        if ($hashBefore -ne $hashAfter) {
            Write-Host "  [ОБНОВЛЕНО] install.ps1 был обновлён — перезапуск с новой версией..." -ForegroundColor Cyan
            $psExe = try {
                (Get-Process -Id $PID).Path
            } catch {
                Write-Host "  [!!] Не удалось определить путь PowerShell; используется powershell.exe" -ForegroundColor Yellow
                "powershell.exe"
            }
            & $psExe -ExecutionPolicy Bypass -File $selfPath @args
            exit
        }
    }
}

$venvDir = Join-Path $repoDir ".venv"

# -- Helpers -------------------------------------------------------------------
function Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Info($msg) { Write-Host "  [--] $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Err($msg)  { Write-Host "  [ERROR] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "  =============================================" -ForegroundColor White
Write-Host "   Code VM — Первоначальная установка         " -ForegroundColor White
Write-Host "  =============================================" -ForegroundColor White
Write-Host ""

# -- 1. Find Python ------------------------------------------------------------
$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 8) {
                $python = $cmd
                Ok "Python найден: $ver"
                break
            }
        }
    } catch { }
}

if (-not $python) {
    Err "Python 3.8+ не найден."
    Write-Host ""
    Write-Host "  Скачай Python здесь:" -ForegroundColor Yellow
    Write-Host "    https://www.python.org/downloads/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  ВАЖНО: при установке поставь галочку 'Add Python to PATH'" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Нажми Enter для выхода"
    exit 1
}

# -- 2. Create virtual environment ---------------------------------------------
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvCfg    = Join-Path $venvDir "pyvenv.cfg"

# A valid venv must have both python.exe AND pyvenv.cfg.
# If python.exe exists but pyvenv.cfg is absent the venv is corrupt — remove and recreate.
if ((Test-Path $venvPython) -and (Test-Path $venvCfg)) {
    Ok "Виртуальное окружение уже существует (.venv)"
} else {
    if (Test-Path $venvDir) {
        Info "Обнаружено повреждённое виртуальное окружение — пересоздание..."
        Remove-Item -Recurse -Force $venvDir
    }
    Info "Создание виртуального окружения (.venv)..."
    & $python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Err "Не удалось создать виртуальное окружение."
        Read-Host "  Нажми Enter для выхода"
        exit 1
    }
    Ok "Виртуальное окружение создано"
}

# -- 3. Upgrade pip ------------------------------------------------------------
# Use python -m pip (not pip.exe) so Windows can replace the executable.
# 2>&1 | Out-Null merges stderr→stdout then discards all output, preventing
# $ErrorActionPreference="Stop" from aborting on a NativeCommandError.
# try/catch makes the upgrade non-fatal (a newer pip is nice but not required).
Info "Обновление pip..."
try { & $venvPython -m pip install --upgrade pip 2>&1 | Out-Null } catch { }
Ok "pip обновлён"

# -- 4. Install Flask + requests -----------------------------------------------
Info "Установка Flask + requests..."
& $venvPython -m pip install flask requests --quiet
if ($LASTEXITCODE -ne 0) {
    Err "Не удалось установить Flask/requests."
    Read-Host "  Нажми Enter для выхода"
    exit 1
}
Ok "Flask + requests установлены"

# -- 5. Install requirements.txt (optional extras) -----------------------------
$reqFile = Join-Path $repoDir "requirements.txt"
if (Test-Path $reqFile) {
    Info "Установка requirements.txt (зависимости Telegram-бота)..."
    & $venvPython -m pip install -r $reqFile --quiet 2>$null
    Ok "requirements.txt обработан"
}

# -- 5b. Install Playwright Chromium browser (needed for screenshots & agent) --
Info "Установка браузера Chromium для Playwright (скриншоты и автономный агент)..."
try {
    & $venvPython -m playwright install chromium 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Ok "Playwright Chromium установлен (скриншоты и авто-агент работают)"
    } else {
        Warn "Playwright Chromium не установлен — скриншоты будут недоступны"
    }
} catch {
    Warn "Playwright Chromium не установлен — скриншоты будут недоступны"
}

# -- 4. Bundle Monaco Editor locally ------------------------------------------
Write-Host ""
Write-Host "  =============================================" -ForegroundColor White
Write-Host "   Скачивание Monaco Editor (автономная работа)" -ForegroundColor White
Write-Host "  =============================================" -ForegroundColor White
Write-Host ""

$bundleScript = Join-Path $repoDir "vm\bundle_monaco.ps1"
if (Test-Path $bundleScript) {
    Info "Скачивание файлов Monaco Editor для работы без интернета..."
    try {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $bundleScript
        Ok "Monaco Editor скачан (редактор работает без интернета)"
    } catch {
        Warn "Не удалось скачать Monaco — будет использован CDN автоматически."
    }
} else {
    Warn "vm\bundle_monaco.ps1 не найден — будет использован CDN."
}

# -- 5. Install Ollama automatically ------------------------------------------
Write-Host ""
Write-Host "  =============================================" -ForegroundColor White
Write-Host "   Ollama (AI-функции)                        " -ForegroundColor White
Write-Host "  =============================================" -ForegroundColor White
Write-Host ""

$ollamaInstalled = $false
try {
    $ollamaVer = & ollama --version 2>&1
    if ($LASTEXITCODE -eq 0) { $ollamaInstalled = $true }
} catch { }

if ($ollamaInstalled) {
    Ok "Ollama уже установлена: $ollamaVer"
} else {
    Info "Загрузка установщика Ollama (может занять минуту)..."
    $ollamaInstaller = Join-Path $env:TEMP "OllamaSetup.exe"
    try {
        Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" `
            -OutFile $ollamaInstaller -UseBasicParsing
        Info "Установка Ollama в тихом режиме..."
        $proc = Start-Process -FilePath $ollamaInstaller `
            -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" `
            -Wait -PassThru
        if ($proc.ExitCode -eq 0) {
            # Make ollama visible in current session PATH
            $ollamaDir = Join-Path $env:LOCALAPPDATA "Programs\Ollama"
            if (Test-Path $ollamaDir) {
                $env:PATH = "$ollamaDir;$env:PATH"
            }
            Ok "Ollama установлена"
            $ollamaInstalled = $true
        } else {
            Warn "Установка Ollama завершилась с кодом $($proc.ExitCode)."
            Warn "Установи вручную позже: https://ollama.com/download"
        }
    } catch {
        Warn "Ошибка при загрузке или установке: $_"
        Warn "Установи вручную позже: https://ollama.com/download"
    }
}

# -- 6. Start AI model download in background ---------------------------------
$modelName = "qwen3-vl:8b"
if ($ollamaInstalled) {
    $modelPresent = $false
    try {
        $list = & ollama list 2>&1
        # Check each line: model name should appear as the first token on a data line
        foreach ($line in ($list -split "`n")) {
            if ($line -match "^\s*$([regex]::Escape($modelName))\b") {
                $modelPresent = $true
                break
            }
        }
    } catch { }

    if ($modelPresent) {
        Ok "AI-модель уже скачана ($modelName)"
    } else {
        Info "Запуск загрузки AI-модели в фоне ($modelName, ~5 ГБ)..."
        Info "Откроется маленькое окно с прогрессом загрузки — можно работать пока оно работает."
        # Write a temp batch file instead of embedding && in ArgumentList
        # (avoids HTML-entity corruption when the script is downloaded via a browser)
        $pullBat = Join-Path $env:TEMP "ollama_pull_model.bat"
        "@echo off`r`necho Загружаю $modelName ...`r`nollama pull $modelName`r`necho [OK] Модель готова!`r`npause`r`ndel `"%~f0`"`r`n" |
            Out-File -FilePath $pullBat -Encoding ascii
        Start-Process cmd -ArgumentList "/c `"$pullBat`"" -WindowStyle Minimized
        Ok "Загрузка модели запущена в фоне"
    }
} else {
    Warn "Ollama не установлена — загрузка модели пропущена."
    Write-Host "  Чтобы включить AI-функции позже:" -ForegroundColor Yellow
    Write-Host "    1. Установи с https://ollama.com/download" -ForegroundColor Cyan
    Write-Host "    2. Выполни: ollama pull $modelName" -ForegroundColor Cyan
    Write-Host "    3. Выполни: ollama serve" -ForegroundColor Cyan
}

# -- 7. Create Desktop shortcut ------------------------------------------------
Write-Host ""
Write-Host "  =============================================" -ForegroundColor White
Write-Host "   Ярлык на Рабочем столе                     " -ForegroundColor White
Write-Host "  =============================================" -ForegroundColor White
Write-Host ""

Info "Создание ярлыка «Code VM» на Рабочем столе..."
$desktopPath     = [Environment]::GetFolderPath("Desktop")
$startPs1        = Join-Path $repoDir "start.ps1"
$createShortcut  = Join-Path $repoDir "vm\create_shortcut.ps1"
$shortcutOk = $false
if (Test-Path $createShortcut) {
    try {
        $psExeLocal = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        if (-not (Test-Path $psExeLocal)) { $psExeLocal = "powershell.exe" }
        $proc = Start-Process -FilePath $psExeLocal `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$createShortcut`" -NoLaunch" `
            -WorkingDirectory $repoDir -Wait -PassThru -ErrorAction Stop
        if ($proc.ExitCode -eq 0) {
            $shortcutOk = $true
            Ok "Ярлык создан — значок «Code VM» на Рабочем столе"
        } else {
            Warn "create_shortcut.ps1 завершился с кодом $($proc.ExitCode)."
        }
    } catch {
        Warn "Создание ярлыка не удалось: $_"
    }
}

# Fallback: inline shortcut creation if the script approach failed
if (-not $shortcutOk) {
    Warn "Пробую создать ярлык напрямую (резервный способ)..."
    $psExe    = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path $psExe)) { $psExe = "powershell.exe" }
    $shortcutPath = Join-Path $desktopPath "Code VM.lnk"
    try {
        $shell    = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath       = $psExe
        $shortcut.Arguments        = "-NoProfile -ExecutionPolicy Bypass -File `"$startPs1`""
        $shortcut.WorkingDirectory = $repoDir
        $shortcut.Description      = "Launch Code VM - Monaco Editor with Ollama AI"
        $shortcut.WindowStyle      = 1
        $customIco = Join-Path $repoDir "vm\static\code_vm.ico"
        if (Test-Path $customIco) {
            $shortcut.IconLocation = "$customIco,0"
        } else {
            $icoLib = Join-Path $env:SystemRoot "System32\shell32.dll"
            $shortcut.IconLocation = if (Test-Path $icoLib) { "$icoLib,77" } else { "$psExe,0" }
        }
        $shortcut.Save()
        $shortcutOk = $true
        Ok "Ярлык создан (резервный способ) — значок «Code VM» на Рабочем столе"
    } catch {
        Warn "Резервный способ тоже не сработал: $_"
    }
}

# -- 8. Copy self-discovering launcher to Desktop------------------------------
$launcherSrc  = Join-Path $repoDir "ЗАПУСТИТЬ.bat"
$launcherDest = Join-Path $desktopPath "ЗАПУСТИТЬ.bat"
if (Test-Path $launcherSrc) {
    try {
        Copy-Item -Path $launcherSrc -Destination $launcherDest -Force
        Ok "Резервный лаунчер скопирован: «ЗАПУСТИТЬ.bat» на Рабочем столе (двойной клик если основной ярлык не работает)"
    } catch {
        Warn "Не удалось скопировать ЗАПУСТИТЬ.bat на Рабочий стол: $_"
    }
}
# Also copy the PS1 helper script that ЗАПУСТИТЬ.bat delegates to
$zapustitPsSrc  = Join-Path $repoDir "zapustit.ps1"
$zapustitPsDest = Join-Path $desktopPath "zapustit.ps1"
if (Test-Path $zapustitPsSrc) {
    try {
        Copy-Item -Path $zapustitPsSrc -Destination $zapustitPsDest -Force
    } catch {
        Warn "Не удалось скопировать zapustit.ps1 на Рабочий стол: $_"
    }
}

# Copy ЗАПУСТИТЬ_ВМ.bat (launcher for retrained VM with drgr-visor model)
$vmLauncherSrc  = Join-Path $repoDir "ЗАПУСТИТЬ_ВМ.bat"
$vmLauncherDest = Join-Path $desktopPath "ЗАПУСТИТЬ_ВМ.bat"
if (Test-Path $vmLauncherSrc) {
    try {
        Copy-Item -Path $vmLauncherSrc -Destination $vmLauncherDest -Force
        Ok "Лаунчер Visor VM скопирован: «ЗАПУСТИТЬ_ВМ.bat» на Рабочем столе"
    } catch {
        Warn "Не удалось скопировать ЗАПУСТИТЬ_ВМ.bat на Рабочий стол: $_"
    }
}

# Copy ПЕРЕУЧИТЬ_ВМ.bat (standalone retrain-only launcher)
$retrainSrc  = Join-Path $repoDir "ПЕРЕУЧИТЬ_ВМ.bat"
$retrainDest = Join-Path $desktopPath "ПЕРЕУЧИТЬ_ВМ.bat"
if (Test-Path $retrainSrc) {
    try {
        Copy-Item -Path $retrainSrc -Destination $retrainDest -Force
        Ok "Лаунчер переобучения скопирован: «ПЕРЕУЧИТЬ_ВМ.bat» на Рабочем столе"
    } catch {
        Warn "Не удалось скопировать ПЕРЕУЧИТЬ_ВМ.bat на Рабочий стол: $_"
    }
}

# Copy ОБНОВИТЬ.bat (update launcher — download and install new files)
$updateRuSrc  = Join-Path $repoDir "ОБНОВИТЬ.bat"
$updateRuDest = Join-Path $desktopPath "ОБНОВИТЬ.bat"
if (Test-Path $updateRuSrc) {
    try {
        Copy-Item -Path $updateRuSrc -Destination $updateRuDest -Force
        Ok "Лаунчер обновления скопирован: «ОБНОВИТЬ.bat» на Рабочем столе"
    } catch {
        Warn "Не удалось скопировать ОБНОВИТЬ.bat на Рабочий стол: $_"
    }
}

# -- 9. Done -------------------------------------------------------------------
Write-Host ""
Write-Host "  =============================================" -ForegroundColor Green
Write-Host "   Установка завершена!                       " -ForegroundColor Green
Write-Host "  =============================================" -ForegroundColor Green
Write-Host ""
if ($shortcutOk) {
    Write-Host "  На Рабочем столе теперь есть:" -ForegroundColor White
    Write-Host "    'Code VM.lnk'        — ярлык (двойной клик для запуска)" -ForegroundColor Cyan
    Write-Host "    'ЗАПУСТИТЬ.bat'      — резервный лаунчер (работает откуда угодно)" -ForegroundColor Cyan
    Write-Host "    'ЗАПУСТИТЬ_ВМ.bat'   — Code VM + создание переученной модели drgr-visor" -ForegroundColor Green
    Write-Host "    'ПЕРЕУЧИТЬ_ВМ.bat'   — только переучить (создать/обновить drgr-visor)" -ForegroundColor Green
    Write-Host "    'ОБНОВИТЬ.bat'       — скачать и установить новые файлы (обновление)" -ForegroundColor Yellow
} else {
    Write-Host "  [!!] Ярлык не удалось создать автоматически." -ForegroundColor Yellow
    Write-Host "  Чтобы создать значок «Code VM» на Рабочем столе, выполни:" -ForegroundColor Yellow
    Write-Host "    powershell -ExecutionPolicy Bypass -File `"$repoDir\vm\create_shortcut.ps1`"" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Резервный лаунчер «ЗАПУСТИТЬ.bat» может уже быть на Рабочем столе." -ForegroundColor White
}
Write-Host ""
Write-Host "  Или запусти напрямую из PowerShell (вставь это):" -ForegroundColor White
Write-Host "    powershell -ExecutionPolicy Bypass -File `"$repoDir\start.ps1`"" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Затем открой в браузере:" -ForegroundColor White
Write-Host "    http://localhost:5000/" -ForegroundColor Cyan
Write-Host ""
if ($shortcutOk) {
    Write-Host "  Совет: чтобы пересоздать ярлык в любое время, выполни:" -ForegroundColor DarkGray
    Write-Host "    powershell -ExecutionPolicy Bypass -File `"$repoDir\vm\create_shortcut.ps1`"" -ForegroundColor DarkGray
    Write-Host ""
}

# -- 10. Auto-launch the VM so browser opens immediately after first-time setup ---
# Skip auto-launch only when the caller passes -NoLaunch (e.g., CI/test runs).
if ($args -notcontains '-NoLaunch') {
    if (Test-Path $startPs1) {
        Write-Host "  [-->] Запуск Code VM (браузер откроется автоматически)..." -ForegroundColor Cyan
        $psExeLaunch = try { (Get-Process -Id $PID).Path } catch { "powershell.exe" }
        Start-Process -FilePath $psExeLaunch `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$startPs1`"" `
            -WorkingDirectory $repoDir
    }
}
