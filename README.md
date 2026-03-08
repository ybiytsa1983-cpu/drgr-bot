# 🤖 drgr-bot + ⚡ Code VM

A Telegram bot with a built-in **AI-powered code editor** (Code VM) and **Android navigator PWA** — all runnable from a laptop.

---

## 🚨 ВАЖНО — читай сюда, если ничего не работает

> **В PowerShell перед любым скриптом ВСЕГДА нужна точка с обратным слэшем: `.\`**
>
> ❌ Неправильно: `install.ps1`, `vm.ps1`, `start.ps1`  
> ✅ Правильно:   `.\install.ps1`, `.\vm.ps1`, `.\start.ps1`

Нажатие Enter на имени файла без `.\` в PowerShell не запускает скрипт — это ошибка, о которой PowerShell сам предупреждает.

### 🟢 Самый простой способ запустить (без ввода команд):

**Дважды кликни по файлу `start.bat`** в Проводнике Windows — откроет редактор автоматически.

### 🟢 Если нужно из PowerShell — одна правильная команда:

```
.\start.ps1
```

### 🟢 Если скрипты заблокированы («running scripts is disabled») — одна команда:

```
powershell -ExecutionPolicy Bypass -File vm\create_shortcut.ps1
```

Создаст ярлык на Рабочем столе **и сразу откроет редактор** в браузере.

---

## 🔴 ERR_CONNECTION_REFUSED — сайт localhost не позволяет установить соединение

Это значит сервер не запущен. Причины и решения:

**Причина 1 — Python не установлен.**  
Установи Python 3.8+ с [python.org/downloads](https://python.org/downloads/) — **обязательно ставь галочку «Add Python to PATH»**.  
Потом запусти снова:
```
.\start.ps1
```
или двойной клик по `start.bat`.

**Причина 2 — сервер был остановлен** (закрыл окно, нажал Ctrl+C).  
Просто запусти снова:
```
.\start.ps1
```

**Причина 3 — не запустил установку** перед запуском VM.  
Запусти полную установку один раз:
```
.\install.ps1
```
Потом `.\start.ps1`.

> 💡 Начиная с последнего обновления сервер запускается **в фоне** и **НЕ останавливается** при закрытии окна терминала. Если у тебя старая версия — сделай `git pull`.

---

## ⚠️ Уже клонировал раньше? Сначала обнови!

Если папка `drgr-bot` у тебя **уже есть**, открой PowerShell, перейди в неё и обнови:

```
cd C:\путь\к\папке\drgr-bot
git pull
```

После этого запусти:

```
.\start.ps1
```

---

## ⚡ Быстрый старт — одна команда

### Windows (первый раз, свежая установка)

**Шаг 1 — клонируй репозиторий** (один раз):

```
git clone -b copilot/create-monaco-code-generator https://github.com/ybiytsa1983-cpu/drgr-bot.git
cd drgr-bot
```

**Шаг 2 — запусти**:

```
.\start.ps1
```

> 💡 **Важно:** в PowerShell перед командой нужно писать `.\`
> `start.ps1` (без точки и слэша) **не работает** — пишите `.\start.ps1`

> ⚠️ **Не копируй строки с `PS C:\...>` из примеров!**  
> Копируй только саму команду. Символы `PS C:\...>` — это приглашение терминала,
> а `PS` в PowerShell — это псевдоним (alias) команды `Get-Process`, что вызовет ошибку.

Первый запуск установит всё автоматически (~1-2 мин), потом откроет браузер.  
Каждый следующий раз: просто откроет браузер.

> ⚠️ Если PowerShell говорит **"running scripts is disabled"** — выполни это один раз:
> ```
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> Потом снова запусти `.\start.ps1`.

**Альтернатива — двойной клик** по `start.bat` в Проводнике (без PowerShell, просто мышкой).

Если скрипты отключены, можно создать ярлык на Рабочем столе **и сразу запустить редактор** одной командой:
```
powershell -ExecutionPolicy Bypass -File vm\create_shortcut.ps1
```

### macOS / Linux

```bash
git clone -b copilot/create-monaco-code-generator https://github.com/ybiytsa1983-cpu/drgr-bot.git
cd drgr-bot
chmod +x start.sh && ./start.sh
```

---

## 🤖 AI (Ollama) — ничего настраивать не нужно

Если Ollama уже запущена (на **любом** порту 11434-11444) — Code VM найдёт её **автоматически**.

```
# Просто запусти Ollama отдельно (если не запущена):
ollama serve
```

Хочешь другой порт? Укажи явно перед запуском:
```
$env:OLLAMA_HOST = "http://localhost:11435"
.\start.ps1
```

---

## 🖥 Что откроется в браузере

| URL | Описание |
|-----|---------|
| `http://localhost:5000/` | ⚡ Code VM — Monaco Editor с AI-генерацией кода |
| `http://localhost:5000/navigator/` | 🧭 DRGRNav — PWA-навигатор для Android |
| `http://localhost:5000/challenges` | 🚀 Сложные AI-задачи (JSON) |

---

## 🚀 Возможности VM

| Функция | Горячая клавиша |
|---------|----------------|
| ⚡ Генерация кода с AI | Ctrl+G → ввод промпта → Code |
| 🌐 Генерация HTML-страницы | Ctrl+G → HTML |
| ▶ Запуск кода (Python / JS) | Ctrl+Enter |
| 🔍 Линтинг / проверка | Ctrl+Shift+K |
| 🚀 Сложные AI-задачи | вкладка Tasks |
| 💬 AI-чат по коду | вкладка AI |

---

## 🧭 DRGRNav — навигатор для Android

Открой `http://ТВОЙ_IP:5000/navigator/` в Chrome на Android → ⋮ → **Добавить на главный экран**.

```bash
# Узнать свой IP:
ipconfig | findstr IPv4     # Windows
ip route get 1 | awk '{print $NF; exit}'  # Linux/macOS
```

---

## 🗂 Структура проекта

```
drgr-bot/
├── start.ps1              # ← ЗАПУСК в PowerShell: .\start.ps1
├── start.bat              # ← ЗАПУСК двойным кликом или из cmd.exe
├── start.sh               # ← ЗАПУСК в Linux/macOS: ./start.sh
├── vm/
│   ├── server.py          # Flask backend
│   ├── static/index.html  # Monaco Editor UI
│   └── start_vm.bat       # Windows double-click launcher
├── navigator/             # Android PWA
├── vm.bat                 # Запуск без переустановки (Windows)
├── vm.sh                  # Запуск без переустановки (Linux/macOS)
├── install.bat            # Только установка (Windows)
└── install.ps1            # Только установка (PowerShell)
```

---

## 🛠 Переменные окружения

| Переменная | По умолчанию | Описание |
|-----------|-------------|---------|
| `VM_PORT` | `5000` | Порт сервера Code VM |
| `OLLAMA_HOST` | *(авто)* | URL Ollama, если нужен нестандартный порт |
| `OLLAMA_TIMEOUT` | `120` | Таймаут AI-ответа (секунды) |
| `OLLAMA_DEFAULT_MODEL` | *(авто)* | Принудительно выбрать модель |

---

## 📋 Требования

- Python 3.8+
- pip (идёт вместе с Python)
- Современный браузер (Chrome, Edge, Firefox)
- Ollama (опционально, для AI-функций — [ollama.com/download](https://ollama.com/download))

