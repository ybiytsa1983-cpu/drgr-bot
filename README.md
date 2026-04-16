# 🤖 DRGR VM — AI-powered Browser Extension

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![Ollama](https://img.shields.io/badge/Ollama-compatible-green)](https://ollama.ai)
[![Stars](https://img.shields.io/github/stars/ybiytsa1983-cpu/drgr-bot?style=social)](https://github.com/ybiytsa1983-cpu/drgr-bot/stargazers)

> **DRGR VM** — локальная AI-среда разработчика прямо в браузере. Monaco-редактор + live-превью + чат с локальными LLM (Ollama / LM Studio) + генерация 3D / изображений / статей + автономный браузер-агент.

---

## ✨ Возможности

| Модуль | Описание |
|--------|----------|
| 💬 **ИИ Чат** | Ollama / LM Studio / GLM / Remote VM |
| 📝 **Monaco Редактор** | HTML/CSS/JS с live-preview в Визоре |
| 🔍 **Поиск + Статья** | DDG + Wikipedia + Reddit → HTML-статья |
| 🧊 **GLTF Генератор** | 3D-фигуры (Three.js) → .gltf файл |
| 🎨 **Арт / SD** | Stable Diffusion + ComfyUI локально |
| 📱 **Android** | Kotlin/Flutter код + APK + Appetize.io |
| 🦆 **Goose Агент** | Автономный code-агент (block/goose) |
| 🌐 **3D Генерация** | TripoSR / Hunyuan3D-2 / NVIDIA 3D |
| ☁️ **Colab VM** | Удалённые модели через ngrok |
| 🎬 **Видеоредактор** | EDL-сценарии для монтажа через LLM |
| 🤖 **Telegram бот** | Управление VM из Telegram |

---

## 🚀 Быстрый старт

### Вариант 1 — PowerShell (рекомендуется)

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1
```

Скрипт автоматически:
1. Проверит Python 3.10+
2. Установит зависимости
3. Обнаружит и запустит Ollama (если установлена)
4. Проверит свободность порта
5. Запустит VM сервер на `http://localhost:5000`
6. Откроет браузер

### Вариант 2 — BAT файл

```
ЗАПУСТИТЬ_БОТА.bat
```

### Вариант 3 — Установка одной командой

```powershell
irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/run.ps1" | iex
```

---

## 📦 Структура

```
drgr-bot/
├── vm/                  # Flask сервер (основной бэкенд)
├── extension/           # Chrome/Edge расширение
├── local-comet-patch/   # Патч для локального Comet
├── bot.py               # Telegram бот
├── start.ps1            # Запуск (Windows)
├── start_vm.ps1         # Запуск только VM
├── update.ps1           # Обновление
└── requirements.txt
```

---

## 🔧 Требования

- Windows 10/11 (PowerShell 5+)
- Python 3.10+
- [Ollama](https://ollama.ai) (рекомендуется) или LM Studio
- Chrome / Edge браузер

---

## 🐛 Известные проблемы (в работе)

- [ ] Чат-зал — `about:blank#blocked` (CSP конфликт)
- [ ] GLTF 3D-превью не рендерится (WebGL инициализация)
- [ ] localStorage недоступен в Визоре (sandbox)
- [ ] Async/Canvas тесты зависают в диагностике

---

## 💖 Поддержать проект

Проект разрабатывается одним человеком в свободное время.

- ⭐ **Поставь звезду** — помогает другим найти проект
- ☕ **Boosty** — https://boosty.to/drgr (подписка от 100 ₽/мес)
- 💳 **Донат** — реквизиты по запросу в Telegram
- 🤝 **Pull Request** — любой фикс приветствуется

### Что даёт поддержка:
| Уровень | Цена | Что получаешь |
|---------|------|---------------|
| ☕ Кофе | 100 ₽/мес | Имя в README |
| 🥈 Supporter | 300 ₽/мес | Приоритет в issues |
| 🥇 Pro | 700 ₽/мес | Ранний доступ к фичам + закрытый чат |
| 💎 Sponsor | 2000 ₽/мес | Кастомная фича по запросу |

---

## 📄 Лицензия

MIT — используй свободно, форкай, улучшай. Ссылка на оригинал приветствуется.

---

<p align="center">
  Сделано с ❤️ в Санкт-Петербурге
</p>
