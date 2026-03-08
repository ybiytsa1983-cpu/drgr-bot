# 🤖 drgr-bot + ⚡ Code VM

A Telegram bot with a built-in **AI-powered code editor** (Code VM) and **Android navigator PWA** — all runnable from a laptop in a few commands.

---

## ⚡ Быстрый старт — одна команда

### Windows — скачай и запусти

```powershell
git clone -b copilot/create-monaco-code-generator https://github.com/ybiytsa1983-cpu/drgr-bot.git
cd drgr-bot
.\start.bat
```

> **Первый раз:** установит всё нужное автоматически (~1-2 мин), потом откроет браузер.  
> **Каждый следующий раз:** просто откроет браузер.

Или **двойной клик по `start.bat`** в Проводнике — браузер откроется сам.

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
```bat
REM Windows cmd:
set OLLAMA_HOST=http://localhost:11435
.\start.bat
```
```powershell
# PowerShell:
$env:OLLAMA_HOST = "http://localhost:11435"
.\start.bat
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
├── start.bat              # ← ОДНА КОМАНДА (Windows)
├── start.sh               # ← ОДНА КОМАНДА (Linux/macOS)
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

