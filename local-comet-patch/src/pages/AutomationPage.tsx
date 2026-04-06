import { useCallback, useEffect, useState } from 'react';
import {
  cancelTask,
  createTask,
  getAutomationStatus,
  getTasks,
  solveCaptcha,
} from '../lib/vmApi';
import type { AutomationStatus, CaptchaSolveResponse, TaskResponse } from '../types/vm';

export default function AutomationPage() {
  const [autoStatus, setAutoStatus] = useState<AutomationStatus | null>(null);
  const [tasks, setTasks] = useState<TaskResponse[]>([]);
  const [captchaResult, setCaptchaResult] = useState<CaptchaSolveResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Form state
  const [captchaUrl, setCaptchaUrl] = useState('');
  const [captchaMethod, setCaptchaMethod] = useState<'auto' | 'click' | '2captcha'>('auto');
  const [captchaSiteKey, setCaptchaSiteKey] = useState('');
  const [taskUrl, setTaskUrl] = useState('');
  const [taskCycles, setTaskCycles] = useState(1);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [s, t] = await Promise.all([getAutomationStatus(), getTasks()]);
      setAutoStatus(s);
      setTasks(Array.isArray(t) ? t : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка подключения');
    }
  }, []);

  // Load on mount
  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleSolveCaptcha = async () => {
    if (!captchaUrl.trim()) return;
    setBusy(true);
    setError(null);
    setCaptchaResult(null);
    try {
      const res = await solveCaptcha({
        method: captchaMethod,
        page_url: captchaUrl,
        site_key: captchaSiteKey || undefined,
      });
      setCaptchaResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'CAPTCHA запрос не выполнен');
    } finally {
      setBusy(false);
    }
  };

  const handleCreateTask = async () => {
    if (!taskUrl.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createTask({
        task_type: 'browse',
        url: taskUrl,
        cycles: taskCycles,
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка создания задачи');
    } finally {
      setBusy(false);
    }
  };

  const handleCancel = async (id: string) => {
    try {
      await cancelTask(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка отмены');
    }
  };

  return (
    <main className="mx-auto w-full max-w-[1200px] space-y-6 p-4 text-slate-100 lg:p-6">
      <header>
        <h1 className="text-2xl font-bold">⚡ Автоматизация</h1>
        <p className="text-sm text-slate-400">
          Selenium задачи, CAPTCHA обход, автологин
        </p>
      </header>

      {error ? (
        <div className="rounded-lg border border-red-800 bg-red-950/40 p-3 text-sm text-red-200">
          {error}
        </div>
      ) : null}

      {/* Status tiles */}
      {autoStatus ? (
        <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            { label: 'Selenium', ok: autoStatus.selenium_available },
            { label: '2captcha', ok: autoStatus.twocaptcha_available },
            { label: 'LLM', ok: autoStatus.llm_available },
            { label: 'Активных задач', ok: autoStatus.active_tasks > 0, detail: String(autoStatus.active_tasks) },
          ].map((t) => (
            <div
              key={t.label}
              className="flex items-center gap-3 rounded-lg border border-slate-700 bg-slate-800/60 px-4 py-3"
            >
              <span
                className={`inline-block h-2.5 w-2.5 rounded-full ${t.ok ? 'bg-emerald-400' : 'bg-red-500'}`}
              />
              <div>
                <div className="text-sm font-medium">{t.label}</div>
                {t.detail ? <div className="text-xs text-slate-400">{t.detail}</div> : null}
              </div>
            </div>
          ))}
        </section>
      ) : null}

      {/* CAPTCHA solver */}
      <section className="space-y-3 rounded-xl border border-slate-700 bg-slate-900/80 p-4">
        <h3 className="text-sm font-semibold text-slate-200">🔓 CAPTCHA</h3>
        <div className="flex flex-wrap gap-2">
          <select
            value={captchaMethod}
            onChange={(e) => setCaptchaMethod(e.target.value as typeof captchaMethod)}
            className="rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-200"
          >
            <option value="auto">Auto (click → 2captcha)</option>
            <option value="click">Click (бесплатный)</option>
            <option value="2captcha">2captcha (платный)</option>
          </select>
          <input
            value={captchaUrl}
            onChange={(e) => setCaptchaUrl(e.target.value)}
            placeholder="URL страницы"
            className="flex-1 rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500"
          />
          <input
            value={captchaSiteKey}
            onChange={(e) => setCaptchaSiteKey(e.target.value)}
            placeholder="Site key (для 2captcha)"
            className="w-48 rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500"
          />
          <button
            type="button"
            onClick={handleSolveCaptcha}
            disabled={busy || !captchaUrl.trim()}
            className="rounded-md bg-amber-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
          >
            Решить
          </button>
        </div>
        {captchaResult ? (
          <pre className="rounded-md bg-slate-800 p-3 text-xs text-slate-300">
            {JSON.stringify(captchaResult, null, 2)}
          </pre>
        ) : null}
      </section>

      {/* Task creator */}
      <section className="space-y-3 rounded-xl border border-slate-700 bg-slate-900/80 p-4">
        <h3 className="text-sm font-semibold text-slate-200">📋 Создать задачу</h3>
        <div className="flex flex-wrap gap-2">
          <input
            value={taskUrl}
            onChange={(e) => setTaskUrl(e.target.value)}
            placeholder="URL задачи"
            className="flex-1 rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500"
          />
          <input
            type="number"
            value={taskCycles}
            onChange={(e) => setTaskCycles(Number(e.target.value) || 1)}
            min={1}
            max={100}
            className="w-20 rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-200"
          />
          <button
            type="button"
            onClick={handleCreateTask}
            disabled={busy || !taskUrl.trim()}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
          >
            Создать
          </button>
          <button
            type="button"
            onClick={refresh}
            className="rounded-md border border-slate-600 px-4 py-2 text-sm text-slate-200"
          >
            🔄
          </button>
        </div>
      </section>

      {/* Tasks list */}
      {tasks.length > 0 ? (
        <section className="space-y-2 rounded-xl border border-slate-700 bg-slate-900/80 p-4">
          <h3 className="text-sm font-semibold text-slate-200">Задачи</h3>
          <div className="space-y-2">
            {tasks.map((task) => (
              <div
                key={task.id}
                className="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-800/60 p-3"
              >
                <div className="text-sm">
                  <span className="font-mono text-xs text-slate-400">{task.id.slice(0, 8)}</span>
                  {' '}
                  <span
                    className={
                      task.status === 'completed'
                        ? 'text-emerald-400'
                        : task.status === 'failed'
                          ? 'text-red-400'
                          : 'text-amber-300'
                    }
                  >
                    {task.status}
                  </span>
                  {task.result ? (
                    <span className="ml-2 text-xs text-slate-400">{task.result}</span>
                  ) : null}
                  {task.error ? (
                    <span className="ml-2 text-xs text-red-400">{task.error}</span>
                  ) : null}
                </div>
                {task.status !== 'completed' && task.status !== 'failed' ? (
                  <button
                    type="button"
                    onClick={() => handleCancel(task.id)}
                    className="rounded-md bg-red-700 px-3 py-1 text-xs text-white"
                  >
                    Отмена
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </main>
  );
}
