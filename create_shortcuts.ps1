#Requires -Version 5.1
<#
.SYNOPSIS
    Создаёт ярлыки DRGR Bot на Рабочем столе пользователя.
.DESCRIPTION
    Создаёт два .lnk-ярлыка прямо на Рабочем столе:
      - "DRGR Bot.lnk"           -> ЗАПУСТИТЬ_БОТА.bat  (запуск бота)
      - "DRGR Bot - Obnovit.lnk" -> ОБНОВИТЬ.bat        (обновление)
    Вызывается из УСТАНОВИТЬ.bat, ОБНОВИТЬ.bat и update.ps1.
#>

param(
    # Папка проекта. По умолчанию — та же папка, где лежит этот скрипт.
    [string]$BotDir = $PSScriptRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

try {
    $desktop = [System.Environment]::GetFolderPath('Desktop')
    $ws      = New-Object -ComObject WScript.Shell

    $s1 = $ws.CreateShortcut("$desktop\DRGR Bot.lnk")
    $s1.TargetPath       = Join-Path $BotDir 'ЗАПУСТИТЬ_БОТА.bat'
    $s1.WorkingDirectory = $BotDir
    $s1.Description      = 'Zapustit DRGR Bot'
    $s1.Save()

    $s2 = $ws.CreateShortcut("$desktop\DRGR Bot - Obnovit.lnk")
    $s2.TargetPath       = Join-Path $BotDir 'ОБНОВИТЬ.bat'
    $s2.WorkingDirectory = $BotDir
    $s2.Description      = 'Obnovit DRGR Bot'
    $s2.Save()

    Write-Host "  OK  Ярлыки созданы на Рабочем столе: 'DRGR Bot.lnk' и 'DRGR Bot - Obnovit.lnk'" -ForegroundColor Green
    exit 0
} catch {
    Write-Host "  WARN  Не удалось создать ярлыки: $_" -ForegroundColor Yellow
    exit 1
}
