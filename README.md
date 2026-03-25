# drgr-bot

Многофункциональный Telegram-бот на Python с поддержкой ИИ, обработки фото/видео, веб-поиска и генерации статей.

---

## 📋 Требования

| Программа | Версия | Ссылка для скачивания |
|-----------|--------|-----------------------|
| Python | 3.10+ | https://www.python.org/downloads/ |
| Git | любая | https://git-scm.com/download/win |

> ⚠️ При установке Python обязательно поставьте галочку **"Add Python to PATH"**

---

## 🚀 Первоначальная установка на Windows

### Вариант 1 — через батник (рекомендуется)

1. Скачайте репозиторий одним из способов:
   - нажмите **Code → Download ZIP** на GitHub, распакуйте в любую папку
   - **или** выполните в папке где хотите хранить бота:
     ```
     git clone https://github.com/ybiytsa1983-cpu/drgr-bot.git
     cd drgr-bot
     ```
2. Дважды щёлкните **`УСТАНОВИТЬ.bat`**
3. Следуйте инструкциям на экране — скрипт сам установит зависимости, создаст `.env` и откроет его в блокноте
4. Заполните `.env` (см. раздел «Настройка .env» ниже) и сохраните
5. Бот запустится автоматически
6. На Рабочем столе появится ярлык **`drgr-bot`** — дважды щёлкните по нему в любой момент, чтобы снова запустить бота

### Вариант 2 — через PowerShell

Откройте PowerShell в папке с ботом и выполните по очереди:

```powershell
# 1. Установить зависимости
pip install -r requirements.txt

# 2. Создать .env из шаблона
Copy-Item .env.example .env

# 3. Открыть .env для редактирования
notepad .env

# 4. После сохранения .env — запустить бота
python bot.py
```

---

## ⚙️ Настройка .env

Откройте файл `.env` и заполните обязательные поля:

```ini
# Токен бота — получить у @BotFather в Telegram
BOT_TOKEN=123456789:ABCdefGHI...

# API-ключ Hugging Face — получить на https://huggingface.co/settings/tokens
HUGGINGFACE_API_KEY=hf_...
```

Остальные параметры можно оставить по умолчанию.

---

## 🔄 Обновление до последней версии

### Через батник на рабочем столе

Дважды щёлкните **`ОБНОВИТЬ.bat`** — он:
1. Сохранит резервную копию текущей версии
2. Скачает обновления (`git pull`)
3. Обновит зависимости (`pip install`)
4. Спросит, понравилось ли обновление — при отказе откатится назад
5. Перезапустит бот

### Через PowerShell вручную

```powershell
# Запустить скрипт обновления (с автоматическим перезапуском бота)
powershell -ExecutionPolicy Bypass -File update.ps1

# Запустить скрипт обновления БЕЗ перезапуска бота
powershell -ExecutionPolicy Bypass -File update.ps1 -SkipRestart
```

> Если PowerShell не разрешает запуск скриптов, выполните один раз:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

---

## ▶️ Запуск бота

Используйте ярлык **`drgr-bot`** на Рабочем столе (создаётся автоматически при установке), **или** дважды щёлкните **`ЗАПУСТИТЬ.bat`** в папке с ботом, **или** запустите PowerShell-скрипт:

```powershell
powershell -ExecutionPolicy Bypass -File ЗАПУСТИТЬ.ps1
```

Или просто:

```powershell
python bot.py
```

---

## 🛑 Остановка бота

Закройте окно консоли **или** выполните в PowerShell:

```powershell
Get-Process python | Where-Object { $_.MainWindowTitle -match 'drgr' } | Stop-Process -Force
```

---

## 📁 Структура проекта

```
drgr-bot/
├── bot.py              # Основной файл бота
├── requirements.txt    # Зависимости Python
├── .env                # Ваши секреты (НЕ коммитить!)
├── .env.example        # Шаблон переменных окружения
├── УСТАНОВИТЬ.bat      # Первоначальная установка (Windows)
├── ЗАПУСТИТЬ.bat       # Запуск бота одним кликом (Windows)
├── ЗАПУСТИТЬ.ps1       # Запуск бота через PowerShell
├── ОБНОВИТЬ.bat        # Обновление + откат (Windows)
├── update.ps1          # PowerShell-скрипт обновления
└── vm/                 # Веб-сервер (Flask)
    ├── server.py
    └── static/
```

---

## ❓ Частые проблемы

| Проблема | Решение |
|----------|---------|
| `python` не найден | Переустановите Python с галочкой «Add to PATH» |
| `git` не найден | Установите git с https://git-scm.com/download/win |
| `BOT_TOKEN` ошибка | Заполните `.env` — токен от @BotFather |
| `HUGGINGFACE_API_KEY` ошибка | Заполните `.env` — ключ с huggingface.co/settings/tokens |
| Скрипт .ps1 не запускается | Выполните: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Бот уже запущен (порт занят) | Закройте старое окно бота или перезагрузите компьютер |