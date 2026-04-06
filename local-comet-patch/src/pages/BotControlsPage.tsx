import { useCallback, useState } from 'react';
import { getBotLog, getBotStatus, startBot, stopBot } from '../lib/vmApi';
import type { BotStatusResponse } from '../types/vm';

export default function BotControlsPage() {
  const [status, setStatus] = useState<BotStatusResponse | null>(null);
  const [log, setLog] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [s, l] = await Promise.all([getBotStatus(), getBotLog()]);
      setStatus(s);
      setLog(l.log ?? '');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка подключения');
    }
  }, []);

  // Load on first render
  const loaded = { current: false };
  if (!loaded.current) {
    loaded.current = true;
    refresh();
  }

  const handleStart = async () => {
    setBusy(true);
    try {
      await startBot();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось запустить');
    } finally {
      setBusy(false);
    }
  };

  const handleStop = async () => {
    setBusy(true);
    try {
      await stopBot();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось остановить');
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto w-full max-w-[1000px] space-y-6 p-4 text-slate-100 lg:p-6">
      <header>
        <h1 className="text-2xl font-bold">🤖 Бот-контроль</h1>
        <p className="text-sm text-slate-400">Управление Telegram ботом</p>
      </header>

      {error ? (
        <div className="rounded-lg border border-red-800 bg-red-950/40 p-3 text-sm text-red-200">
          {error}
        </div>
      ) : null}

      {/* Status + Controls */}
      <section className="flex flex-wrap items-center gap-4 rounded-xl border border-slate-700 bg-slate-900/80 p-4">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block h-3 w-3 rounded-full ${status?.running ? 'bg-emerald-400' : 'bg-red-500'}`}
          />
          <span className="text-sm">
            {status?.running ? `Работает (PID ${status.pid})` : 'Остановлен'}
          </span>
        </div>
        <button
          type="button"
          onClick={handleStart}
          disabled={busy || status?.running === true}
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          ▶ Запустить
        </button>
        <button
          type="button"
          onClick={handleStop}
          disabled={busy || !status?.running}
          className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          ⏹ Остановить
        </button>
        <button
          type="button"
          onClick={refresh}
          className="rounded-md border border-slate-600 px-4 py-2 text-sm text-slate-200"
        >
          🔄 Обновить
        </button>
      </section>

      {/* Log */}
      <section className="space-y-2 rounded-xl border border-slate-700 bg-slate-900/80 p-4">
        <h3 className="text-sm font-semibold text-slate-200">Лог бота</h3>
        <pre className="max-h-[400px] overflow-auto whitespace-pre-wrap rounded-md bg-slate-800 p-3 text-xs text-slate-300">
          {log || 'Лог пуст.'}
        </pre>
      </section>
    </main>
  );
}
