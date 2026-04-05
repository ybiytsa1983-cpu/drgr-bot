import type { RunCodeResponse } from '../types/editor';

interface ResultPanelProps {
  result: RunCodeResponse | null;
  error: string | null;
}

export function ResultPanel({ result, error }: ResultPanelProps) {
  return (
    <div className="space-y-3 rounded-xl border border-slate-700 bg-slate-900/80 p-4">
      <h3 className="text-sm font-semibold text-slate-200">Console output</h3>

      {error ? (
        <pre className="whitespace-pre-wrap rounded-md bg-red-950/40 p-3 text-sm text-red-200">{error}</pre>
      ) : null}

      {result?.stdout ? (
        <pre className="whitespace-pre-wrap rounded-md bg-slate-800 p-3 text-sm text-emerald-200">{result.stdout}</pre>
      ) : null}

      {result?.stderr ? (
        <pre className="whitespace-pre-wrap rounded-md bg-red-950/40 p-3 text-sm text-red-200">{result.stderr}</pre>
      ) : null}

      {!error && !result?.stdout && !result?.stderr ? (
        <p className="text-sm text-slate-400">No logs yet. Run code to see output.</p>
      ) : null}
    </div>
  );
}
