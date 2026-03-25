@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ======================================
echo   ZAPUSK DRGR BOT + VM
echo ======================================
echo.

REM Proverka Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [OSHIBKA] Python ne ustanovlen! Ustanovite Python 3.10+
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Python nayden
echo.

REM Obnovleniye iz GitHub
echo Obnovleniye iz GitHub...
git fetch origin main
if errorlevel 1 (
    echo Preduprezhdenie: ne udalos poluchit obnovleniya. Prodolzhayu...
    goto :SKIP_RESET
)
git reset --hard origin/main
if errorlevel 1 (
    echo Preduprezhdenie: ne udalos primenit obnovleniya. Prodolzhayu...
)
:SKIP_RESET
echo.

REM Ustanovka zavisimostey
echo Ustanovka zavisimostey...
pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo Preduprezhdenie: nekotorye zavisimosti ne ustanovilis
)
echo.

REM Proverka .env
if not exist .env (
    echo [OSHIBKA] Fayl .env ne nayden!
    echo Sozdayte fayl .env s BOT_TOKEN=vash_token
    echo.
    echo Primer:  echo BOT_TOKEN=1234567890:AABBcc...  ^> .env
    pause
    exit /b 1
)

echo Fayl .env nayden
echo.

REM Zapusk VM servera v otdelnom okne
echo Zapusk VM servera...
start "DRGR VM Server" cmd /k "cd /d %CD% && python vm/server.py"

REM Zaderzhka 3 sek dlya zapuska VM
timeout /t 3 /nobreak > nul

REM Zapusk Telegram bota v otdelnom okne
echo Zapusk Telegram bota...
start "DRGR Telegram Bot" cmd /k "cd /d %CD% && python bot.py"

echo.
echo Bot i VM zapushcheny v otdelnykh oknakh!
echo.
echo Dlya ostanovki zakroyte okna "DRGR VM Server" i "DRGR Telegram Bot"
echo Veb-interfeys VM: http://localhost:5000
echo.
pause
