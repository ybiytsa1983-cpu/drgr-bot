import { useCallback, useState } from 'react';
import { runResearch } from '../lib/vmApi';
import type { ResearchResponse } from '../types/vm';

export default function ArticleGeneratorPage() {
  const [query, setQuery] = useState('');
  const [maxSources, setMaxSources] = useState(8);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ResearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = useCallback(async () => {
    if (!query.trim() || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await runResearch({ query, max_sources: maxSources });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка генерации');
    } finally {
      setLoading(false);
    }
  }, [query, maxSources, loading]);

  return (
    <main className="mx-auto w-full max-w-[1000px] space-y-6 p-4 text-slate-100 lg:p-6">
      <header>
        <h1 className="text-2xl font-bold">📰 Генератор статей</h1>
        <p className="text-sm text-slate-400">
          DDG-поиск + скрапинг + LLM → готовая статья
        </p>
      </header>

      {/* Input */}
      <section className="space-y-3 rounded-xl border border-slate-700 bg-slate-900/80 p-4">
        <div className="flex flex-col gap-2 md:flex-row">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleGenerate();
            }}
            placeholder="Тема статьи, например: Лучшие фреймворки 2025"
            className="flex-1 rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
          />
          <input
            type="number"
            value={maxSources}
            onChange={(e) => setMaxSources(Number(e.target.value) || 8)}
            min={1}
            max={20}
            title="Макс. источников"
            className="w-20 rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-200"
          />
          <button
            type="button"
            onClick={handleGenerate}
            disabled={loading || !query.trim()}
            className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
          >
            {loading ? '⏳ Генерация…' : '🚀 Генерировать'}
          </button>
        </div>
      </section>

      {error ? (
        <div className="rounded-lg border border-red-800 bg-red-950/40 p-3 text-sm text-red-200">
          {error}
        </div>
      ) : null}

      {result ? (
        <>
          {/* Article */}
          <section className="space-y-2 rounded-xl border border-slate-700 bg-slate-900/80 p-4">
            <h3 className="text-sm font-semibold text-emerald-400">Статья</h3>
            <div className="whitespace-pre-wrap text-sm text-slate-200">{result.article}</div>
          </section>

          {/* Sources */}
          {result.sources && result.sources.length > 0 ? (
            <section className="space-y-2 rounded-xl border border-slate-700 bg-slate-900/80 p-4">
              <h3 className="text-sm font-semibold text-slate-200">Источники</h3>
              <ul className="space-y-1">
                {result.sources.map((s, i) => (
                  <li key={i} className="text-xs">
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-indigo-400 hover:underline"
                    >
                      {s.title || s.url}
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
