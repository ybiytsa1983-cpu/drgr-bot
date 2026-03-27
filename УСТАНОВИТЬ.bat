@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

:: ===================================================================
::  УСТАНОВИТЬ.bat  -  Первичная установка drgr-bot
::  Скачайте этот файл и запустите - он сделает всё сам:
::   1. Клонирует репозиторий на Рабочий стол
::   2. Создаёт файл .env с токеном бота
::   3. Устанавливает зависимости Python
::   4. Запускает VM-сервер (бот управляется из веб-интерфейса)
:: ===================================================================

title drgr-bot - Установка

echo.
echo +----------------------------------------------+
echo ^|        drgr-bot  -  Мастер установки         ^|
echo +----------------------------------------------+
echo.

:: -- Целевая папка на Рабочем столе ------------------------------------
set "DEST=%USERPROFILE%\Desktop\drgr-bot"
set "REPO=https://github.com/ybiytsa1983-cpu/drgr-bot.git"

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
    echo  Убедитесь, что при установке отмечена галочка
    echo  "Add Python to PATH", затем запустите этот файл снова.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('python --version 2^>^&1') do echo  Найден: %%V
echo.

:: -- 2. Проверка Git ----------------------------------------------------
echo  [2/5] Проверка Git...
git --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Git не найден!
    echo.
    echo  Установите Git for Windows:
    echo    https://git-scm.com/download/win
    echo.
    echo  После установки запустите этот файл снова.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('git --version 2^>^&1') do echo  Найден: %%V
echo.

:: -- 3. Клонирование репозитория ----------------------------------------
echo  [3/5] Клонирование репозитория в %DEST%...
echo.

if exist "%DEST%\.git" (
    echo  Папка уже существует. Обновляем...
    cd /d "%DEST%"
    git fetch origin main > nul 2>&1
    git reset --hard origin/main
    if errorlevel 1 (
        echo  [ОШИБКА] Не удалось обновить репозиторий.
        pause
        exit /b 1
    )
    echo  Репозиторий обновлён.
) else (
    if exist "%DEST%" (
        echo  Папка "%DEST%" существует, но не является git-репозиторием.
        echo  Возможно, она повреждена или удалена случайно.
        echo.
        :ASK_DELETE
        set "DEL_CHOICE="
        set /p "DEL_CHOICE= Удалить папку и скачать заново? (да/нет): "
        if /i "!DEL_CHOICE!"=="да"  goto :DO_DELETE
        if /i "!DEL_CHOICE!"=="yes" goto :DO_DELETE
        if /i "!DEL_CHOICE!"=="д"   goto :DO_DELETE
        if /i "!DEL_CHOICE!"=="y"   goto :DO_DELETE
        if /i "!DEL_CHOICE!"=="нет" goto :CANT_PROCEED
        if /i "!DEL_CHOICE!"=="no"  goto :CANT_PROCEED
        if /i "!DEL_CHOICE!"=="н"   goto :CANT_PROCEED
        if /i "!DEL_CHOICE!"=="n"   goto :CANT_PROCEED
        echo  Введите "да" или "нет".
        goto :ASK_DELETE

        :CANT_PROCEED
        echo  Переименуйте или удалите папку "%DEST%" вручную и запустите снова.
        echo.
        pause
        exit /b 1

        :DO_DELETE
        echo  Удаляем старую папку...
        rmdir /s /q "%DEST%"
        if errorlevel 1 (
            echo  [ОШИБКА] Не удалось удалить папку. Удалите её вручную и запустите снова.
            pause
            exit /b 1
        )
        echo  Папка удалена.
    )
    git clone "%REPO%" "%DEST%"
    if errorlevel 1 (
        echo.
        echo  [ОШИБКА] Не удалось клонировать репозиторий.
        echo  Проверьте подключение к интернету и попробуйте снова.
        echo.
        pause
        exit /b 1
    )
    echo  Репозиторий успешно склонирован.
)
echo.

:: -- Переходим в папку проекта ------------------------------------------
cd /d "%DEST%"

:: -- 4. Установка зависимостей ------------------------------------------
echo  [4/5] Установка зависимостей Python...
pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo.
    echo  [ПРЕДУПРЕЖДЕНИЕ] Некоторые зависимости не установились.
    echo  Попробуйте запустить вручную: pip install -r requirements.txt
    echo.
) else (
    echo  Зависимости установлены успешно.
)
echo.

:: -- 5. Настройка файла .env --------------------------------------------
echo  [5/5] Настройка файла .env...
echo.

if exist "%DEST%\.env" (
    echo  Файл .env уже существует. Используем его.
    echo  (Чтобы изменить токен - откройте .env в блокноте)
) else (
    echo  Файл .env не найден. Нужно ввести токен Telegram-бота.
    echo.
    echo  Как получить токен:
    echo    1. Откройте Telegram и найдите @BotFather
    echo    2. Отправьте /newbot и следуйте инструкциям
    echo    3. Скопируйте токен вида: 1234567890:AABBccDDeeFFggHH...
    echo.
    set "BOT_TOKEN="
    set /p "BOT_TOKEN= Введите BOT_TOKEN: "

    if "!BOT_TOKEN!"=="" (
        echo.
        echo  [ОШИБКА] Токен не введён. Создайте файл .env вручную:
        echo    1. Откройте Блокнот
        echo    2. Напишите: BOT_TOKEN=ваш_токен
        echo    3. Сохраните как "%DEST%\.env"
        echo.
        pause
        exit /b 1
    )

    echo BOT_TOKEN=!BOT_TOKEN!> "%DEST%\.env"
    echo  Файл .env создан.
)
echo.

:: -- Создание значка на Рабочем столе ---------------------------------
echo  Создание значка на Рабочем столе...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws=New-Object -ComObject WScript.Shell; $sc=$ws.CreateShortcut('%USERPROFILE%\Desktop\ЗАПУСТИТЬ БОТА.lnk'); $sc.TargetPath='%DEST%\ЗАПУСТИТЬ_БОТА.bat'; $sc.WorkingDirectory='%DEST%'; $sc.Description='Запустить VM-сервер drgr-bot'; $sc.IconLocation='%SystemRoot%\System32\cmd.exe,0'; $sc.Save()" > nul 2>&1
if errorlevel 1 (
    echo  [ПРЕДУПРЕЖДЕНИЕ] Значок не создан. Откройте ЗАПУСТИТЬ_БОТА.bat вручную.
) else (
    echo  Значок "ЗАПУСТИТЬ БОТА" создан на Рабочем столе!
)
echo.

:: -- Итог ---------------------------------------------------------------
echo +----------------------------------------------+
echo ^|       Установка завершена успешно!           ^|
echo +----------------------------------------------+
echo ^|  Значок "ЗАПУСТИТЬ БОТА" создан на Рабочем  ^|
echo ^|  столе — дважды кликните чтобы запустить.   ^|
echo ^|                                              ^|
echo ^|  Для обновления используйте файл:            ^|
echo ^|    ОБНОВИТЬ.bat                              ^|
echo +----------------------------------------------+
echo.
echo  Папка проекта: %DEST%
echo.

:: -- Предлагаем сразу запустить бота -----------------------------------
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
echo  Запуск VM-сервера...
call "%DEST%\ЗАПУСТИТЬ_БОТА.bat"
goto :END

:SKIP_LAUNCH
echo.
echo  Готово! Дважды кликните ЗАПУСТИТЬ_БОТА.bat для запуска.
echo.

:END
pause
