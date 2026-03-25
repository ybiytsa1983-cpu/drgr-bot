#Requires -Version 5.1
<#
.SYNOPSIS
    Создаёт ярлыки DRGR Bot на Рабочем столе пользователя.
.DESCRIPTION
    Создаёт три .lnk-ярлыка прямо на Рабочем столе:
      - "DRGR Bot.lnk"                  -> ЗАПУСТИТЬ_БОТА.bat        (запуск бота)
      - "DRGR Bot - Obnovit.lnk"        -> ОБНОВИТЬ.bat              (обновление)
      - "DRGR Bot - Rasshirenie.lnk"    -> УСТАНОВИТЬ_РАСШИРЕНИЕ.bat (браузерное расширение)
    Ярлыки получают иконку из extension/icons/icon128.png (ICO-конвертация через .NET).
    Вызывается из УСТАНОВИТЬ.bat, ОБНОВИТЬ.bat и update.ps1.
#>

param(
    # Папка проекта. По умолчанию — та же папка, где лежит этот скрипт.
    [string]$BotDir = $PSScriptRoot
)

$ErrorActionPreference = 'Continue'

# ── Конвертируем PNG -> ICO если иконок ещё нет ───────────────────────────
function Ensure-Icon([string]$botDir) {
    $icoPath = Join-Path $botDir 'extension\icons\icon.ico'
    if (Test-Path $icoPath) { return $icoPath }

    # Генерируем PNG сначала (если нет)
    $pngPath = Join-Path $botDir 'extension\icons\icon128.png'
    if (-not (Test-Path $pngPath)) {
        $py = Join-Path $botDir 'extension\make_icons.py'
        if ((Get-Command python -ErrorAction SilentlyContinue) -and (Test-Path $py)) {
            python $py 2>&1 | Out-Null
        }
    }

    # PNG -> ICO через System.Drawing
    if (Test-Path $pngPath) {
        try {
            Add-Type -AssemblyName System.Drawing -ErrorAction Stop
            $bmp    = [System.Drawing.Bitmap]::FromFile($pngPath)
            $ms     = New-Object System.IO.MemoryStream
            $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
            $bmp.Dispose()

            $icoStream = [System.IO.File]::Create($icoPath)
            # ICO header (1 image)
            $header = [byte[]](0,0, 1,0, 1,0)
            $icoStream.Write($header, 0, 6)
            $imgData = $ms.ToArray()
            $ms.Dispose()
            # Image directory entry: 128x128, 0 colors, 0 planes, 0 bpp, size, offset(22)
            $sz     = [BitConverter]::GetBytes([int]$imgData.Length)
            $offset = [BitConverter]::GetBytes([int]22)
            $entry  = [byte[]](128, 128, 0, 0, 0, 0, 0, 0) + $sz + $offset
            $icoStream.Write($entry, 0, 16)
            $icoStream.Write($imgData, 0, $imgData.Length)
            $icoStream.Close()
            return $icoPath
        } catch {
            return $null
        }
    }
    return $null
}

try {
    $desktop = [System.Environment]::GetFolderPath('Desktop')
    $ws      = New-Object -ComObject WScript.Shell
    $icoPath = Ensure-Icon $BotDir

    # ── ярлык 1: Запуск бота ──────────────────────────────────────────────
    $s1 = $ws.CreateShortcut("$desktop\DRGR Bot.lnk")
    $s1.TargetPath       = Join-Path $BotDir 'ЗАПУСТИТЬ_БОТА.bat'
    $s1.WorkingDirectory = $BotDir
    $s1.Description      = 'Запустить DRGR Bot'
    if ($icoPath) { $s1.IconLocation = "$icoPath,0" }
    $s1.Save()

    # ── ярлык 2: Обновление ───────────────────────────────────────────────
    $s2 = $ws.CreateShortcut("$desktop\DRGR Bot - Obnovit.lnk")
    $s2.TargetPath       = Join-Path $BotDir 'ОБНОВИТЬ.bat'
    $s2.WorkingDirectory = $BotDir
    $s2.Description      = 'Обновить DRGR Bot'
    if ($icoPath) { $s2.IconLocation = "$icoPath,0" }
    $s2.Save()

    # ── ярлык 3: Браузерное расширение ────────────────────────────────────
    $extBat = Join-Path $BotDir 'УСТАНОВИТЬ_РАСШИРЕНИЕ.bat'
    if (Test-Path $extBat) {
        $s3 = $ws.CreateShortcut("$desktop\DRGR Bot - Rasshirenie.lnk")
        $s3.TargetPath       = $extBat
        $s3.WorkingDirectory = $BotDir
        $s3.Description      = 'Установить браузерное расширение DRGR Bot'
        if ($icoPath) { $s3.IconLocation = "$icoPath,0" }
        $s3.Save()
        Write-Host "  OK  Ярлыки созданы: 'DRGR Bot.lnk', 'DRGR Bot - Obnovit.lnk', 'DRGR Bot - Rasshirenie.lnk'" -ForegroundColor Green
    } else {
        Write-Host "  OK  Ярлыки созданы: 'DRGR Bot.lnk' и 'DRGR Bot - Obnovit.lnk'" -ForegroundColor Green
    }

    if ($icoPath) {
        Write-Host "  OK  Иконка назначена: $icoPath" -ForegroundColor Green
    } else {
        Write-Host "  INFO  Иконка не создана — ярлыки будут со стандартным значком." -ForegroundColor Yellow
    }
    exit 0
} catch {
    Write-Host "  WARN  Не удалось создать ярлыки: $_" -ForegroundColor Yellow
    exit 1
}
