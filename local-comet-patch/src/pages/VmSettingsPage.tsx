import { useCallback, useState } from 'react';
import { getSettings, saveSettings } from '../lib/vmApi';
import type { SettingsData } from '../types/vm';

export default function VmSettingsPage() {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [raw, setRaw] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setError(null);
    setSaved(false);
    try {
      const data = await getSettings();
      setSettings(data);
      // Convert to .env-like text
      const lines = Object.entries(data)
        .map(([k, v]) => `${k}=${v}`)
        .join('\n');
      setRaw(lines);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки настроек');
    }
  }, []);

  // Load once
  const loaded = { current: false };
  if (!loaded.current) {
    loaded.current = true;
    refresh();
  }

  const handleSave = async () => {
    setLoading(true);
    setError(null);
    setSaved(false);
    try {
      const data: SettingsData = {};
      for (const line of raw.split('\n')) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#')) continue;
        const eqIdx = trimmed.indexOf('=');
        if (eqIdx === -1) continue;
        const key = trimmed.slice(0, eqIdx).trim();
        const val = trimmed.slice(eqIdx + 1).trim();
        if (key) data[key] = val;
      }
      await saveSettings(data);
      setSaved(true);
      setSettings(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка сохранения');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="mx-auto w-full max-w-[800px] space-y-6 p-4 text-slate-100 lg:p-6">
      <header>
        <h1 className="text-2xl font-bold">⚙️ Настройки VM</h1>
        <p className="text-sm text-slate-400">Редактирование .env файла через VM API</p>
      </header>

      {error ? (
        <div className="rounded-lg border border-red-800 bg-red-950/40 p-3 text-sm text-red-200">
          {error}
        </div>
      ) : null}

      {saved ? (
        <div className="rounded-lg border border-emerald-800 bg-emerald-950/40 p-3 text-sm text-emerald-200">
          ✅ Настройки сохранены!
        </div>
      ) : null}

      <section className="space-y-3 rounded-xl border border-slate-700 bg-slate-900/80 p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-200">.env</h3>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={refresh}
              className="rounded-md border border-slate-600 px-3 py-1 text-xs text-slate-200"
            >
              🔄 Обновить
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={loading}
              className="rounded-md bg-emerald-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-60"
            >
              {loading ? 'Сохранение…' : '💾 Сохранить'}
            </button>
          </div>
        </div>
        <textarea
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          rows={16}
          className="w-full resize-y rounded-md border border-slate-600 bg-slate-800 p-3 font-mono text-xs text-slate-200"
          placeholder="BOT_TOKEN=xxx&#10;HUGGINGFACE_API_KEY=yyy"
        />
        <p className="text-xs text-slate-500">
          Формат: KEY=VALUE, по одной переменной на строку. Строки начинающиеся с # игнорируются.
        </p>
      </section>

      {/* Current keys preview */}
      {settings ? (
        <section className="space-y-2 rounded-xl border border-slate-700 bg-slate-900/80 p-4">
          <h3 className="text-sm font-semibold text-slate-200">
            Текущие ключи ({Object.keys(settings).length})
          </h3>
          <div className="flex flex-wrap gap-2">
            {Object.keys(settings).map((key) => (
              <span
                key={key}
                className="rounded-md bg-slate-700 px-2 py-1 text-xs text-slate-300"
              >
                {key}
              </span>
            ))}
          </div>
        </section>
      ) : null}
    </main>
  );
}
