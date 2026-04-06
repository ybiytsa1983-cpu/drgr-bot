# local-comet patch: Full VM Integration

Этот патч превращает local-comet в **полноценную панель управления DRGR VM** — со всеми функциями VM-сервера.

## Что включено

### Страницы (React)
| Файл | Описание |
|---|---|
| `src/App.tsx` | Главный layout с боковой навигацией (7 вкладок) |
| `src/pages/VmDashboard.tsx` | Статус VM: Ollama, LM Studio, TG бот, .env |
| `src/pages/VmChatPage.tsx` | Чат с AI (Ollama / LM Studio) через /chat |
| `src/pages/EditorPage.tsx` | Monaco Editor + Run + AI + Live Preview |
| `src/pages/ArticleGeneratorPage.tsx` | Генератор статей (DDG + LLM) через /research |
| `src/pages/BotControlsPage.tsx` | Управление TG ботом (start/stop/log) |
| `src/pages/AutomationPage.tsx` | Selenium задачи, CAPTCHA обход, автологин |
| `src/pages/VmSettingsPage.tsx` | Редактор .env через /settings |

### API / Типы
| Файл | Описание |
|---|---|
| `src/lib/vmApi.ts` | Клиент для всех VM API эндпоинтов |
| `src/lib/editorApi.ts` | Клиент для Editor server API |
| `src/types/vm.ts` | TypeScript типы для VM API |
| `src/types/editor.ts` | TypeScript типы для Editor |

### Компоненты
| Файл | Описание |
|---|---|
| `src/components/CodeEditor.tsx` | Monaco Editor обёртка |
| `src/components/EditorToolbar.tsx` | Тулбар для редактора |
| `src/components/PreviewFrame.tsx` | Iframe для предпросмотра |
| `src/components/ResultPanel.tsx` | Панель вывода stdout/stderr |

### Backend (server/)
| Файл | Описание |
|---|---|
| `server/index.ts` | Express-сервер: Editor API + VM прокси |

## Установка

### 1) Frontend зависимости

```bash
npm i @monaco-editor/react monaco-editor react react-dom
npm i -D @types/react @types/react-dom
```

### 2) Backend зависимости

```bash
cd server
npm i
```

### 3) Переменные окружения

#### server/.env
```env
EDITOR_SERVER_PORT=5052
VM_URL=http://localhost:5001
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=your_key_here
AI_MODEL=gpt-4o-mini
```

#### Frontend .env
```env
VITE_EDITOR_API_URL=http://localhost:5052
VITE_VM_URL=http://localhost:5001
```

## Запуск

### Шаг 1: Запустить VM сервер
```bash
python vm/server.py
# Порт 5001 (по умолчанию)
```

### Шаг 2: Запустить Editor server
```bash
cd local-comet-patch/server
npm run dev
# Порт 5052
```

### Шаг 3: Запустить frontend
```bash
npm run dev -- --port 5051
# Откройте http://localhost:5051
```

### Быстрый запуск (Windows)
Используйте `ЗАПУСТИТЬ_БОТА.bat` или `START_LOCAL.bat` для запуска VM-сервера, а потом:
```bash
cd local-comet-patch/server && npm run dev
```

## Обновление
```bash
git pull origin main
cd local-comet-patch/server && npm install
```

## Архитектура

```
Browser (localhost:5051)
  ├── Frontend (React + Vite)
  │     ├── VM API → localhost:5001 (vm/server.py)
  │     └── Editor API → localhost:5052 (server/index.ts)
  │
  └── server/index.ts (localhost:5052)
        ├── /api/editor/run — Code execution
        ├── /api/editor/ai-generate — AI code gen
        └── /api/vm/* → Proxy to VM server
```

## Ограничения

- `python` и `javascript/typescript` run в Editor server работают в безопасном режиме (без реального выполнения). Подключите изолированный sandbox для полного выполнения кода.
- CAPTCHA methods `click` и `stealth` требуют Chrome/Chromium + Selenium на сервере.
