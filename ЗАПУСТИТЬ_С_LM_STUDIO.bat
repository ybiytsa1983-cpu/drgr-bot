<# 2>nul
@echo off
:: ============================================================
::  DRGR — Запуск с LM Studio + Ollama + VM + Telegram-бот
::
::  Этот батник находит и запускает LM Studio (порт 1234),
::  затем запускает Ollama, VM-сервер и Telegram-бот.
::
::  Использование:
::    ЗАПУСТИТЬ_С_LM_STUDIO.bat [BOT_TOKEN] [LM_STUDIO_EXE]
::
::  Примеры:
::    ЗАПУСТИТЬ_С_LM_STUDIO.bat
::    ЗАПУСТИТЬ_С_LM_STUDIO.bat 1234567890:AAxx...
::    ЗАПУСТИТЬ_С_LM_STUDIO.bat "" "C:\Program Files\LM Studio\LM Studio.exe"
:: ============================================================

set "TOKEN_ARG=%~1"
set "LMS_EXE=%~2"

if not "%LMS_EXE%"=="" (
    if not "%TOKEN_ARG%"=="" (
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ЗАПУСТИТЬ_С_LM_STUDIO.ps1" -Token "%TOKEN_ARG%" -LmStudioExe "%LMS_EXE%"
    ) else (
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ЗАПУСТИТЬ_С_LM_STUDIO.ps1" -LmStudioExe "%LMS_EXE%"
    )
) else if not "%TOKEN_ARG%"=="" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ЗАПУСТИТЬ_С_LM_STUDIO.ps1" -Token "%TOKEN_ARG%"
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ЗАПУСТИТЬ_С_LM_STUDIO.ps1"
)
exit /b
#>
# PowerShell fallback when bat is run directly from PS console
$f = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$t = if ($args.Count -gt 0) { $args[0] } else { "" }
$e = if ($args.Count -gt 1) { $args[1] } else { "" }
if ($e) { & (Join-Path $f 'ЗАПУСТИТЬ_С_LM_STUDIO.ps1') -Token $t -LmStudioExe $e }
elseif ($t) { & (Join-Path $f 'ЗАПУСТИТЬ_С_LM_STUDIO.ps1') -Token $t }
else { & (Join-Path $f 'ЗАПУСТИТЬ_С_LM_STUDIO.ps1') }
