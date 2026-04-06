import { useCallback, useEffect, useState } from 'react';
import { getModels, getVmStatus } from '../lib/vmApi';
import type { ModelsResponse, VmHealthData } from '../types/vm';

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 rounded-full ${ok ? 'bg-emerald-400' : 'bg-red-500'}`}
    />
  );
}

interface StatusTileProps {
  label: string;
  ok: boolean;
  detail?: string;
}

function StatusTile({ label, ok, detail }: StatusTileProps) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-700 bg-slate-800/60 px-4 py-3">
      <StatusDot ok={ok} />
      <div>
        <div className="text-sm font-medium text-slate-100">{label}</div>
        {detail ? <div className="text-xs text-slate-400">{detail}</div> : null}
      </div>
    </div>
  );
}

export default function VmDashboard() {
  const [health, setHealth] = useState<VmHealthData | null>(null);
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [statusRes, modelsRes] = await Promise.all([getVmStatus(), getModels()]);
      setHealth(statusRes.data);
      setModels(modelsRes);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось подключиться к VM');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 15_000);
    return () => clearInterval(interval);
  }, [refresh]);

  return (
    <main className="mx-auto w-full max-w-[1200px] space-y-6 p-4 text-slate-100 lg:p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">🖥️ VM Статус</h1>
          <p className="text-sm text-slate-400">DRGR Virtual Machine Dashboard</p>
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={loading}
          className="rounded-md bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600 disabled:opacity-60"
        >
          {loading ? 'Обновление…' : '🔄 Обновить'}
        </button>
      </header>

      {error ? (
        <div className="rounded-lg border border-red-800 bg-red-950/40 p-4 text-sm text-red-200">
          {error}
        </div>
      ) : null}

      {health ? (
        <>
          {/* Status tiles */}
          <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatusTile
              label="Ollama"
              ok={health.ollama.available}
              detail={health.ollama.url}
            />
            <StatusTile
              label="LM Studio"
              ok={health.lmstudio.available}
              detail={health.lmstudio.url}
            />
            <StatusTile
              label="TG Bot"
              ok={health.bot.running}
              detail={health.bot.pid ? `PID ${health.bot.pid}` : 'Остановлен'}
            />
            <StatusTile
              label=".env файл"
              ok={health.env_exists}
              detail={health.env_exists ? 'Найден' : 'Отсутствует'}
            />
          </section>

          {/* Models */}
          {models ? (
            <section className="space-y-2 rounded-xl border border-slate-700 bg-slate-900/80 p-4">
              <h3 className="text-sm font-semibold text-slate-200">Доступные модели</h3>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <h4 className="mb-1 text-xs font-medium text-emerald-400">Ollama</h4>
                  {models.ollama.length > 0 ? (
                    <ul className="space-y-1">
                      {models.ollama.map((m) => (
                        <li key={m} className="text-xs text-slate-300">
                          • {m}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-slate-500">Нет моделей</p>
                  )}
                </div>
                <div>
                  <h4 className="mb-1 text-xs font-medium text-indigo-400">LM Studio</h4>
                  {models.lmstudio.length > 0 ? (
                    <ul className="space-y-1">
                      {models.lmstudio.map((m) => (
                        <li key={m} className="text-xs text-slate-300">
                          • {m}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-slate-500">Нет моделей</p>
                  )}
                </div>
              </div>
            </section>
          ) : null}
        </>
      ) : !error ? (
        <p className="text-sm text-slate-400">Загрузка…</p>
      ) : null}
    </main>
  );
}
