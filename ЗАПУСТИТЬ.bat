@echo off
setlocal EnableDelayedExpansion
title Code VM - Запуск...
chcp 65001 >nul 2>&1

REM ============================================================
REM  ЗАПУСТИТЬ.bat - положите на Рабочий стол и дважды щёлкните
REM  Автоматически находит папку drgr-bot и запускает Code VM.
REM ============================================================

set "FOUND="

REM --- Ищем папку drgr-bot в стандартных местах ---------------------
for %%D in (
    "%USERPROFILE%\drgr-bot"
    "%USERPROFILE%\Documents\drgr-bot"
    "%USERPROFILE%\Desktop\drgr-bot"
    "%USERPROFILE%\Downloads\drgr-bot"
    "%USERPROFILE%\projects\drgr-bot"
    "%USERPROFILE%\Projects\drgr-bot"
    "%USERPROFILE%\code\drgr-bot"
    "%USERPROFILE%\Code\drgr-bot"
    "C:\drgr-bot"
    "C:\projects\drgr-bot"
    "C:\Projects\drgr-bot"
    "C:\code\drgr-bot"
    "C:\Code\drgr-bot"
    "C:\Users\%USERNAME%\drgr-bot"
    "D:\drgr-bot"
    "D:\projects\drgr-bot"
) do (
    if exist "%%~D\start.bat" (
        set "FOUND=%%~D"
        goto :launch
    )
)

REM --- Ищем через where git и git config --get remote.origin.url ------
git --version >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%F in ('git -C "%USERPROFILE%" rev-parse --show-toplevel 2^>nul') do (
        if exist "%%F\start.bat" (
            set "FOUND=%%F"
            goto :launch
        )
    )
)

REM --- Широкий поиск по C:\ (медленно, последний шанс) ---------------
echo  [Поиск] Ищем папку drgr-bot на диске C:\...
for /f "delims=" %%F in ('dir /b /s /ad "C:\drgr-bot" 2^>nul') do (
    if exist "%%F\start.bat" (
        set "FOUND=%%F"
        goto :launch
    )
)
for /f "delims=" %%F in ('dir /b /s /ad "D:\drgr-bot" 2^>nul') do (
    if exist "%%F\start.bat" (
        set "FOUND=%%F"
        goto :launch
    )
)

REM --- Не нашли -------------------------------------------------------
echo.
echo  ============================================================
echo   ПАПКА drgr-bot НЕ НАЙДЕНА
echo  ============================================================
echo.
echo  Решение - выполните ЭТИ ДВЕ КОМАНДЫ в PowerShell:
echo.
echo    1. Откройте PowerShell (Win+X -> Windows PowerShell)
echo    2. Вставьте:
echo.
echo    cd "%USERPROFILE%"; git clone https://github.com/ybiytsa1983-cpu/drgr-bot; cd drgr-bot; powershell -ExecutionPolicy Bypass -File install.ps1
echo.
echo  После установки на Рабочем столе появится ярлык "Code VM".
echo.
pause
exit /b 1

:launch
echo.
echo  [OK] Найдено: %FOUND%
echo.

REM --- Обновляем из git (тихо) ----------------------------------------
cd /d "%FOUND%"
echo  [Обновление] Получаем последние исправления...
git pull --ff-only --quiet >nul 2>&1
if not errorlevel 1 (
    echo  [OK] Обновление завершено.
) else (
    echo  [OK] Обновление пропущено (нет подключения или нет изменений).
)

REM --- Нормализуем CRLF в .bat файлах (git хранит LF, cmd.exe требует CRLF) --
REM  1) git checkout re-applies .gitattributes eol=crlf rule to all .bat files
git -C "%FOUND%" checkout HEAD -- vm/start_vm.bat install.bat start.bat stop.bat vm.bat >nul 2>&1
REM  2) PowerShell fallback to normalize any remaining .bat files
echo  [CRLF] Нормализуем окончания строк...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem '%FOUND%' -Recurse -Filter *.bat | ForEach-Object { $f=$_.FullName; $t=[IO.File]::ReadAllText($f); $t2=($t -replace [char]13,'') -replace [char]10,([char]13+[char]10); if($t -ne $t2){[IO.File]::WriteAllText($f,$t2)} }" >nul 2>&1

REM --- Пересоздаём ярлык на Рабочем столе(прямая ссылка на start.bat) --------
echo  [Ярлык] Создаём/обновляем ярлык на Рабочем столе...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$bat='%FOUND%\start.bat'; $s=(New-Object -COM WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Code VM.lnk'); $s.TargetPath=$bat; $s.Arguments=''; $s.WorkingDirectory='%FOUND%'; $s.Description='Launch Code VM - Monaco Editor with Ollama AI'; $s.IconLocation=$env:SystemRoot+'\System32\cmd.exe,0'; $s.Save()" ^
  >nul 2>&1
if not errorlevel 1 (
    echo  [OK] Ярлык "Code VM" на Рабочем столе обновлён.
) else (
    echo  [!] Ярлык не создан (нет прав или PowerShell недоступен).
)

REM --- Запускаем ------------------------------------------------------
echo.
echo  [Запуск] Открываем Code VM...
echo.
call "%FOUND%\start.bat"
exit /b 0
