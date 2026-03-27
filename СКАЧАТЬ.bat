@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

:: ===================================================================
::  СКАЧАТЬ.bat  -  Скачать drgr-bot без Git
::
::  Запустите этот файл — он сам:
::   1. Скачает архив проекта с GitHub (через PowerShell, без Git)
::   2. Распакует в папку "drgr-bot" на Рабочем столе
::   3. Установит зависимости Python
::   4. Создаст значок "ЗАПУСТИТЬ БОТА" на Рабочем столе
::
::  Требуется только Python 3.10+  (Git НЕ нужен)
::    https://www.python.org/downloads/
::    (при установке отметьте "Add Python to PATH")
:: ===================================================================

title drgr-bot - Скачать и установить

echo.
echo +================================================+
echo ^|    drgr-bot  -  Скачать и установить           ^|
echo ^|  (без Git — только Python)                     ^|
echo +================================================+
echo.

set "DEST=%USERPROFILE%\Desktop\drgr-bot"
set "ZIP_URL=https://github.com/ybiytsa1983-cpu/drgr-bot/archive/refs/heads/main.zip"
set "ZIP_FILE=%TEMP%\drgr-bot-main.zip"
set "ZIP_DIR=%TEMP%\drgr-bot-main"
set "ENV_BACKUP=%TEMP%\drgr_bot_env_backup.txt"

:: -- 1. Проверка Python -------------------------------------------------
echo  [1/5] Проверка Python...
python --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Python не найден!
    echo.
    echo  Установите Python 3.10 или новее:
    echo    https://www.python.org/downloads/
    echo.
    echo  Важно: при установке поставьте галочку
    echo         "Add Python to PATH", затем запустите снова.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('python --version 2^>^&1') do echo  Найден: %%V
echo.

:: -- 2. Резервная копия .env если есть ---------------------------------
if exist "%DEST%\.env" (
    echo  Найден файл .env (токен) — сохраняем резервную копию...
    copy /y "%DEST%\.env" "%ENV_BACKUP%" > nul
    echo  Токен сохранён.
    echo.
)

:: -- 3. Скачать ZIP с GitHub -------------------------------------------
echo  [2/5] Скачивание файлов с GitHub...
echo  (Это может занять 10-30 секунд)
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%ZIP_FILE%' -UseBasicParsing } catch { Write-Error $_.Exception.Message; exit 1 }"
if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Не удалось скачать файлы.
    echo.
    echo  Возможные причины:
    echo    - Нет подключения к интернету
    echo    - Брандмауэр блокирует PowerShell
    echo.
    echo  Попробуйте скачать вручную:
    echo    %ZIP_URL%
    echo.
    pause
    exit /b 1
)
echo  Файлы скачаны успешно.
echo.

:: -- 4. Распаковка и перенос ------------------------------------------
echo  [3/5] Установка в папку %DEST%...
echo.

:: Удалить старую папку если есть
if exist "%DEST%" (
    echo  Удаление старой папки...
    rd /s /q "%DEST%" 2>nul
    if exist "%DEST%" (
        echo  [ОШИБКА] Не удалось удалить старую папку "%DEST%".
        echo  Возможно файлы открыты. Закройте все окна и попробуйте снова.
        pause
        exit /b 1
    )
)

:: Удалить старую распакованную директорию
if exist "%ZIP_DIR%" rd /s /q "%ZIP_DIR%" 2>nul

:: Распаковать ZIP
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "Expand-Archive -LiteralPath '%ZIP_FILE%' -DestinationPath '%TEMP%' -Force"
if errorlevel 1 (
    echo  [ОШИБКА] Не удалось распаковать архив.
    pause
    exit /b 1
)

:: Переименовать распакованную папку (GitHub добавляет -main)
if exist "%ZIP_DIR%" (
    move /y "%ZIP_DIR%" "%DEST%" > nul
) else (
    :: Попробуем найти папку вручную
    for /d %%D in ("%TEMP%\drgr-bot*") do (
        if not "%%D"=="%DEST%" (
            move /y "%%D" "%DEST%" > nul
            goto :MOVED
        )
    )
    echo  [ОШИБКА] Не удалось найти распакованную папку.
    pause
    exit /b 1
)
:MOVED

:: Удалить ZIP
del /q "%ZIP_FILE%" 2>nul

echo  Файлы установлены в: %DEST%
echo.

:: -- Восстановление .env -----------------------------------------------
if exist "%ENV_BACKUP%" (
    echo  Восстанавливаем сохранённый токен (.env)...
    copy /y "%ENV_BACKUP%" "%DEST%\.env" > nul
    del /q "%ENV_BACKUP%" 2>nul
    echo  Токен восстановлен.
    echo.
)

:: -- 5. Установка зависимостей Python ----------------------------------
echo  [4/5] Установка зависимостей Python...
echo  (Первый раз может занять 1-3 минуты)
echo.
cd /d "%DEST%"
python -m pip install --upgrade pip --quiet
python -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo.
    echo  [ПРЕДУПРЕЖДЕНИЕ] Некоторые пакеты не установились.
    echo  Попробуйте вручную: pip install -r requirements.txt
    echo.
) else (
    echo  Зависимости установлены.
)
echo.

:: -- 6. Создать токен .env если нет ------------------------------------
if not exist "%DEST%\.env" (
    echo  [5/5] Настройка токена...
    echo.
    echo  Для работы бота нужен токен Telegram.
    echo  Как получить:
    echo    1. Откройте Telegram, найдите @BotFather
    echo    2. Отправьте /newbot и следуйте инструкциям
    echo    3. Скопируйте токен (формат: 1234567890:AAAB...)
    echo.
    set "BOT_TOKEN="
    set /p "BOT_TOKEN= Введите BOT_TOKEN: "

    if "!BOT_TOKEN!"=="" (
        echo.
        echo  Токен не введён. Создайте файл .env вручную:
        echo    1. Откройте Блокнот (notepad.exe)
        echo    2. Напишите: BOT_TOKEN=ваш_токен
        echo    3. Сохраните как "%DEST%\.env"
        echo.
    ) else (
        :: Базовая проверка: токен должен содержать ":"
        echo !BOT_TOKEN! | findstr /r ".*:.*" > nul 2>&1
        if errorlevel 1 (
            echo.
            echo  [ПРЕДУПРЕЖДЕНИЕ] Токен выглядит неправильно.
            echo  Корректный формат: 1234567890:AABBccDDeeFFggHH...
            echo  Токен сохранён как введён. Проверьте его в файле .env
            echo.
        )
        echo BOT_TOKEN=!BOT_TOKEN!> "%DEST%\.env"
        echo  Файл .env создан.
    )
    echo.
) else (
    echo  [5/5] Токен (.env) уже есть.
    echo.
)

:: -- 7. Значок на Рабочем столе ----------------------------------------
echo  Создание значка "ЗАПУСТИТЬ БОТА" на Рабочем столе...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws=New-Object -ComObject WScript.Shell; $sc=$ws.CreateShortcut('%USERPROFILE%\Desktop\ЗАПУСТИТЬ БОТА.lnk'); $sc.TargetPath='%DEST%\ЗАПУСТИТЬ_БОТА.bat'; $sc.WorkingDirectory='%DEST%'; $sc.Description='Запустить drgr-bot + VM сервер'; $sc.IconLocation='%SystemRoot%\System32\cmd.exe,0'; $sc.Save()" > nul 2>&1
if errorlevel 1 (
    echo  [ПРЕДУПРЕЖДЕНИЕ] Значок не создан автоматически.
    echo  Откройте вручную: %DEST%\ЗАПУСТИТЬ_БОТА.bat
) else (
    echo  Значок "ЗАПУСТИТЬ БОТА" создан на Рабочем столе!
)
echo.

:: -- Создать значок для папки проекта ----------------------------------
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws=New-Object -ComObject WScript.Shell; $sc=$ws.CreateShortcut('%USERPROFILE%\Desktop\drgr-bot (папка).lnk'); $sc.TargetPath='%DEST%'; $sc.Description='Папка проекта drgr-bot'; $sc.IconLocation='%SystemRoot%\System32\imageres.dll,3'; $sc.Save()" > nul 2>&1
if not errorlevel 1 (
    echo  Значок папки проекта создан: "drgr-bot (папка)" на Рабочем столе.
    echo.
)

:: -- Итог ---------------------------------------------------------------
echo +================================================+
echo ^|       Установка завершена!                     ^|
echo +================================================+
echo ^|                                               ^|
echo ^|  Значок "ЗАПУСТИТЬ БОТА" — запускает бота    ^|
echo ^|  Значок "drgr-bot (папка)" — открывает       ^|
echo ^|    папку с файлами на Рабочем столе           ^|
echo ^|                                               ^|
echo ^|  Папка проекта:                               ^|
echo ^|    %DEST%
echo ^|                                               ^|
echo +================================================+
echo.

:: -- Предложить запустить бота -----------------------------------------
:ASK_LAUNCH
set "LAUNCH="
set /p "LAUNCH= Запустить бота прямо сейчас? (да/нет): "

if /i "!LAUNCH!"=="да"  goto :DO_LAUNCH
if /i "!LAUNCH!"=="yes" goto :DO_LAUNCH
if /i "!LAUNCH!"=="д"   goto :DO_LAUNCH
if /i "!LAUNCH!"=="y"   goto :DO_LAUNCH
if /i "!LAUNCH!"=="нет" goto :SKIP_LAUNCH
if /i "!LAUNCH!"=="no"  goto :SKIP_LAUNCH
if /i "!LAUNCH!"=="н"   goto :SKIP_LAUNCH
if /i "!LAUNCH!"=="n"   goto :SKIP_LAUNCH

echo  Введите "да" или "нет".
goto :ASK_LAUNCH

:DO_LAUNCH
echo.
echo  Запуск...
call "%DEST%\ЗАПУСТИТЬ_БОТА.bat"
goto :END

:SKIP_LAUNCH
echo.
echo  Готово! Используйте значок "ЗАПУСТИТЬ БОТА" на Рабочем столе.
echo.

:END
pause
