<# 2>nul
@echo off
:: ============================================================
::  DRGR — Авто-запуск Colab VM в расширении
::
::  Подключает ВМ из Google Colab (или другого удалённого сервера)
::  к локальному DRGR VM-серверу и открывает браузер на панели Colab.
::
::  Использование:
::    ЗАПУСТИТЬ_COLAB_VM.bat [COLAB_URL] [BOT_TOKEN]
::
::  Примеры:
::    ЗАПУСТИТЬ_COLAB_VM.bat https://xxxx.ngrok-free.app
::    ЗАПУСТИТЬ_COLAB_VM.bat https://xxxx.ngrok-free.app 1234567890:AAxx...
::
::  Если COLAB_URL не указан — скрипт попросит ввести его.
:: ============================================================

set "COLAB_URL=%~1"
set "TOKEN_ARG=%~2"

if not "%COLAB_URL%"=="" (
    if not "%TOKEN_ARG%"=="" (
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ЗАПУСТИТЬ_COLAB_VM.ps1" -ColabUrl "%COLAB_URL%" -Token "%TOKEN_ARG%"
    ) else (
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ЗАПУСТИТЬ_COLAB_VM.ps1" -ColabUrl "%COLAB_URL%"
    )
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ЗАПУСТИТЬ_COLAB_VM.ps1"
)
exit /b
#>
# PowerShell fallback when bat is run directly from PS console
$f = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$c = if ($args.Count -gt 0) { $args[0] } else { "" }
$t = if ($args.Count -gt 1) { $args[1] } else { "" }
if ($c -and $t) { & (Join-Path $f 'ЗАПУСТИТЬ_COLAB_VM.ps1') -ColabUrl $c -Token $t }
elseif ($c) { & (Join-Path $f 'ЗАПУСТИТЬ_COLAB_VM.ps1') -ColabUrl $c }
else { & (Join-Path $f 'ЗАПУСТИТЬ_COLAB_VM.ps1') }
