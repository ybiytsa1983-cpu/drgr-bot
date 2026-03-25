@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ======================================
echo   ZAPUSK DRGR BOT + VM
echo ======================================
echo.

REM Check Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [OSHIBKA] Python ne ustanovlen! Ustanovite Python 3.10+
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Python nayden
echo.

REM Update from GitHub
echo Obnovlenie iz GitHub...
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

REM Install dependencies
echo Ustanovka zavisimostey...
pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo Preduprezhdenie: nekotorye zavisimosti ne ustanovilis
)
echo.

REM Check .env
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

REM Start VM server in separate window
echo Zapusk VM servera...
start "DRGR VM Server" cmd /k "cd /d %CD% && python vm/server.py"

REM Wait 3 seconds for VM to start
timeout /t 3 /nobreak > nul

REM Start Telegram bot in separate window
echo Zapusk Telegram bota...
start "DRGR Telegram Bot" cmd /k "cd /d %CD% && python bot.py"

echo.
echo Bot i VM zapushcheny v otdelnykh oknakh!
echo.
echo Dlya ostanovki zakroyte okna "DRGR VM Server" i "DRGR Telegram Bot"
echo Veb-interfeys VM: http://localhost:5000
echo.
pause
