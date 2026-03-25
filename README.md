# drgr-bot

Telegram-бот с веб-интерфейсом и VM-сервером для управления AI-моделями.

---

## ⚡ Команды PowerShell (быстрый справочник)

Откройте **PowerShell** (Win+X → Windows PowerShell) и вставьте нужную команду:

### 📥 Установить (первый раз)

```powershell
Set-ExecutionPolicy -Scope Process Bypass; git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git "$env:USERPROFILE\Desktop\drgr-bot"; Set-Location "$env:USERPROFILE\Desktop\drgr-bot"; pip install -r requirements.txt; Write-Host "Готово! Укажите токен в файле .env, затем запустите ЗАПУСТИТЬ_БОТА.bat" -ForegroundColor Green
```

### ▶️ Запустить бота (PowerShell-скрипт)

```powershell
Set-ExecutionPolicy -Scope Process Bypass; & "$env:USERPROFILE\Desktop\drgr-bot\run.ps1"
```

Или, находясь уже в папке `drgr-bot`:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\run.ps1
```

> Альтернатива — двойной клик по файлу **`ЗАПУСТИТЬ_БОТА.bat`** на Рабочем столе.

### 🔄 Обновить бота

```powershell
Set-ExecutionPolicy -Scope Process Bypass; & "$env:USERPROFILE\Desktop\drgr-bot\update.ps1"
```

### 🔗 Восстановить ярлыки на Рабочем столе

```powershell
Set-ExecutionPolicy -Scope Process Bypass; & "$env:USERPROFILE\Desktop\drgr-bot\create_shortcuts.ps1"
```

---

## 🚀 Быстрый старт (первая установка)

> **Папка пропала с Рабочего стола?** Выполните шаги ниже — всё восстановится за пару минут.

### Шаг 1 — Установите зависимости (один раз)

| Программа | Зачем | Ссылка |
|-----------|-------|--------|
| **Python 3.10+** | Запуск бота и сервера | https://www.python.org/downloads/ |
| **Git** | Клонирование и обновление репозитория | https://git-scm.com/download/win |

> ⚠️ При установке Python обязательно отметьте **"Add Python to PATH"**.

### Шаг 2 — Скачайте скрипт установки

Выберите удобный способ:

| Способ | Как |
|--------|-----|
| **Двойной клик (bat-файл)** | Скачайте **[УСТАНОВИТЬ.bat](https://github.com/ybiytsa1983-cpu/drgr-bot/raw/main/%D0%A3%D0%A1%D0%A2%D0%90%D0%9D%D0%9E%D0%92%D0%98%D0%A2%D0%AC.bat)** и дважды кликните по нему |
| **PowerShell (одна строка)** | Скопируйте команду ниже и вставьте в PowerShell |

#### Установка через PowerShell (одна строка)

Откройте **PowerShell** (Win+X → Windows PowerShell) и выполните:

```powershell
Set-ExecutionPolicy -Scope Process Bypass; git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git "$env:USERPROFILE\Desktop\drgr-bot"; Set-Location "$env:USERPROFILE\Desktop\drgr-bot"; pip install -r requirements.txt; Write-Host "Готово! Укажите токен в файле .env, затем запустите ЗАПУСТИТЬ_БОТА.bat" -ForegroundColor Green
```

Или если файл `install.ps1` уже скачан локально:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

### Шаг 3 — Запустите установщик

Скрипт автоматически:

1. Клонирует репозиторий в папку `Рабочий стол\drgr-bot`
2. Установит все зависимости Python
3. Попросит ввести токен Telegram-бота (один раз)
4. Создаст ярлыки **прямо на Рабочем столе** для запуска и обновления
5. Предложит сразу запустить бота

---

## ▶️ Запуск бота

После установки используйте **ярлык на Рабочем столе** `DRGR Bot.lnk`, либо bat-файл напрямую:

```
Рабочий стол\drgr-bot\ЗАПУСТИТЬ_БОТА.bat
```

Скрипт запустит два окна:
- **DRGR VM Server** — локальный сервер (`http://localhost:5000`)
- **DRGR Telegram Bot** — Telegram-бот

---

## 🔄 Обновление

Используйте ярлык на Рабочем столе `DRGR Bot - Obnovit.lnk`, либо:

```
Рабочий стол\drgr-bot\ОБНОВИТЬ.bat
```

Или через PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& "$env:USERPROFILE\Desktop\drgr-bot\update.ps1"
```

Скрипт обновит код, установит новые зависимости, восстановит ярлыки на Рабочем столе и предложит откатиться, если что-то пошло не так.

---

## ⚙️ Ручная установка

Если автоматический скрипт не работает, выполните команды вручную.

### Вариант A — CMD / Командная строка

```bat
:: Клонировать репозиторий на Рабочий стол
git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git %USERPROFILE%\Desktop\drgr-bot

:: Перейти в папку
cd %USERPROFILE%\Desktop\drgr-bot

:: Установить зависимости
pip install -r requirements.txt

:: Создать файл .env с токеном бота
echo BOT_TOKEN=ВАШ_ТОКЕН_ЗДЕСЬ > .env
```

Затем запустите `ЗАПУСТИТЬ_БОТА.bat`.

### Вариант B — PowerShell

```powershell
# Разрешить выполнение скриптов в текущем сеансе
Set-ExecutionPolicy -Scope Process Bypass

# Клонировать репозиторий на Рабочий стол
git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git "$env:USERPROFILE\Desktop\drgr-bot"

# Перейти в папку
Set-Location "$env:USERPROFILE\Desktop\drgr-bot"

# Установить зависимости
pip install -r requirements.txt

# Создать файл .env с токеном бота
"BOT_TOKEN=ВАШ_ТОКЕН_ЗДЕСЬ" | Set-Content .env -Encoding UTF8

# Создать ярлыки на Рабочем столе
.\create_shortcuts.ps1
```

Затем запустите `ЗАПУСТИТЬ_БОТА.bat` или ярлык `DRGR Bot.lnk` на Рабочем столе.

### Восстановление ярлыков (если пропали с Рабочего стола)

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& "$env:USERPROFILE\Desktop\drgr-bot\create_shortcuts.ps1"
```

---

## 🔑 Файл .env

Файл `.env` должен находиться в папке `drgr-bot` и содержать токен бота:

```
BOT_TOKEN=1234567890:AABBccDDeeFFggHHiiJJkkLLmmNNooPP
```

Получить токен: откройте Telegram → найдите **@BotFather** → `/newbot`.

---

## 📁 Структура проекта

```
drgr-bot/
├── bot.py                 # Telegram-бот
├── vm/
│   ├── server.py          # VM-сервер (Flask)
│   └── static/
│       └── index.html     # Веб-интерфейс
├── requirements.txt       # Зависимости Python
├── .env                   # Токен бота (не в репозитории!)
├── УСТАНОВИТЬ.bat         # Первичная установка (двойной клик)
├── УСТАНОВИТЬ.ps1         # Первичная установка (PowerShell, Cyrillic alias)
├── install.ps1            # Первичная установка (PowerShell, ASCII имя — для wget)
├── ЗАПУСТИТЬ_БОТА.bat     # Запуск бота и VM-сервера
├── ОБНОВИТЬ.bat           # Обновление до последней версии
├── update.ps1             # Обновление (PowerShell, с откатом)
└── create_shortcuts.ps1   # Создание/восстановление ярлыков на Рабочем столе
```

---

## ❓ Решение проблем

**Ярлыков нет на Рабочем столе (после обновления пусто)**
→ Откройте PowerShell и выполните:
```powershell
Set-ExecutionPolicy -Scope Process Bypass
& "$env:USERPROFILE\Desktop\drgr-bot\create_shortcuts.ps1"
```
Ярлыки `DRGR Bot.lnk` и `DRGR Bot - Obnovit.lnk` появятся на Рабочем столе.

**Папка drgr-bot пропала с Рабочего стола**
→ Запустите `УСТАНОВИТЬ.bat` (скачайте с [main](https://github.com/ybiytsa1983-cpu/drgr-bot/raw/main/%D0%A3%D0%A1%D0%A2%D0%90%D0%9D%D0%9E%D0%92%D0%98%D0%A2%D0%AC.bat)) — он восстановит всё заново.
Или выполните в PowerShell:
```powershell
Set-ExecutionPolicy -Scope Process Bypass; git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git "$env:USERPROFILE\Desktop\drgr-bot"; pip install -r "$env:USERPROFILE\Desktop\drgr-bot\requirements.txt"
```

**"Python не найден"**
→ Установите Python с https://www.python.org/downloads/ (отметьте "Add Python to PATH") и запустите скрипт снова.

**"Git не найден"**
→ Установите Git с https://git-scm.com/download/win и запустите скрипт снова.

**Бот не отвечает в Telegram**
→ Проверьте, что токен в файле `.env` правильный и что окно "DRGR Telegram Bot" открыто и не показывает ошибок.

**VM-сервер недоступен (http://localhost:5000)**
→ Проверьте, что окно "DRGR VM Server" открыто. Если нет — запустите `ЗАПУСТИТЬ_БОТА.bat` снова.