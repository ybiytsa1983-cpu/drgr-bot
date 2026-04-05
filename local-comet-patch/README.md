# local-comet patch: EditorPage (Monaco + Run + AI + Preview)

Этот набор файлов нужно **скопировать в ваш проект `local-comet`** (React + TypeScript + Vite + Tailwind + Wouter).

## 1) Куда копировать

Скопируйте с сохранением структуры:

- `local-comet-patch/src/pages/EditorPage.tsx` -> `local-comet/src/pages/EditorPage.tsx`
- `local-comet-patch/src/components/CodeEditor.tsx` -> `local-comet/src/components/CodeEditor.tsx`
- `local-comet-patch/src/components/EditorToolbar.tsx` -> `local-comet/src/components/EditorToolbar.tsx`
- `local-comet-patch/src/components/PreviewFrame.tsx` -> `local-comet/src/components/PreviewFrame.tsx`
- `local-comet-patch/src/components/ResultPanel.tsx` -> `local-comet/src/components/ResultPanel.tsx`
- `local-comet-patch/src/types/editor.ts` -> `local-comet/src/types/editor.ts`
- `local-comet-patch/src/lib/editorApi.ts` -> `local-comet/src/lib/editorApi.ts`

## 2) Установить npm-пакеты во фронтенде (`local-comet`)

```bash
npm i @monaco-editor/react monaco-editor
```

## 3) Проверить роут `/editor` (Wouter)

В вашем роутере должна быть страница:

- путь: `/editor`
- компонент: `EditorPage`

Если маршрута нет — добавьте его в `src/App.tsx` (или где у вас объявлены `Route`).

## 4) Backend для запуска кода и AI

Скопируйте папку:

- `local-comet-patch/server/*` -> `local-comet/server/*`

Установите зависимости сервера:

```bash
cd server
npm i
```

Запуск сервера:

```bash
npm run dev
```

По умолчанию server API работает на `http://localhost:5052`.

## 5) Переменные окружения (AI)

Создайте `local-comet/server/.env`:

```env
EDITOR_SERVER_PORT=5052
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=your_key_here
AI_MODEL=gpt-4o-mini
```

Если AI-переменные не заданы, endpoint `/api/editor/ai-generate` вернет fallback-код, чтобы UI не падал.

## 6) Переменные окружения фронтенда

В `local-comet/.env` добавьте:

```env
VITE_EDITOR_API_URL=http://localhost:5052
```

## 7) Запуск local-comet (порт 5051)

В `local-comet`:

```bash
npm run dev -- --port 5051
```

## 8) Что уже реализовано в этом патче

- Monaco Editor (`@monaco-editor/react`)
- Кнопка запуска кода (API: `POST /api/editor/run`)
- AI генерация кода (API: `POST /api/editor/ai-generate`)
- Live preview через `iframe srcDoc`
- Панель stdout/stderr

## 9) Важное ограничение

`python` в этом сервере помечен как disabled (безопасный lightweight режим). Для реального Python-run подключите отдельный изолированный раннер/контейнер.
