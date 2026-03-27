#Requires -Version 5.1
<#
.SYNOPSIS
    Скачивает СКАЧАТЬ.bat на Рабочий стол и запускает его.
.DESCRIPTION
    Запустите одной командой в PowerShell (Win+R -> powershell):

        irm https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/download.ps1 | iex

    Скрипт скачает СКАЧАТЬ.bat на Рабочий стол и запустит его.
    СКАЧАТЬ.bat установит drgr-bot без Git (только Python).
#>

$ErrorActionPreference = 'Stop'

$DesktopPath = [System.Environment]::GetFolderPath('Desktop')
$TargetFile  = Join-Path $DesktopPath 'СКАЧАТЬ.bat'

# URL с percent-encoded кириллицей
$FileUrl = 'https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/%D0%A1%D0%9A%D0%90%D0%A7%D0%90%D0%A2%D0%AC.bat'

Write-Host ''
Write-Host '  drgr-bot - загрузка установщика...' -ForegroundColor Cyan
Write-Host ''

try {
    Invoke-WebRequest -Uri $FileUrl -OutFile $TargetFile -UseBasicParsing
    Write-Host "  Файл сохранён: $TargetFile" -ForegroundColor Green
} catch {
    Write-Host "  [ОШИБКА] Не удалось скачать файл: $_" -ForegroundColor Red
    Write-Host ''
    Write-Host '  Попробуйте скачать вручную:' -ForegroundColor Yellow
    Write-Host "  $FileUrl" -ForegroundColor Yellow
    Write-Host ''
    Read-Host '  Нажмите Enter для выхода'
    exit 1
}

Write-Host ''
Write-Host '  Запуск СКАЧАТЬ.bat...' -ForegroundColor Cyan
Write-Host ''

Start-Process -FilePath $TargetFile -Wait
