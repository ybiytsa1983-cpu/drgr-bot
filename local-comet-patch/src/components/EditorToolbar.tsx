import type { EditorLanguage } from '../types/editor';

interface EditorToolbarProps {
  language: EditorLanguage;
  prompt: string;
  isRunning: boolean;
  isGenerating: boolean;
  onLanguageChange: (language: EditorLanguage) => void;
  onPromptChange: (prompt: string) => void;
  onGenerate: () => void;
  onRun: () => void;
  onClearOutput: () => void;
}

const LANGUAGES: EditorLanguage[] = [
  'html',
  'css',
  'javascript',
  'typescript',
  'json',
  'markdown',
  'python',
];

export function EditorToolbar({
  language,
  prompt,
  isRunning,
  isGenerating,
  onLanguageChange,
  onPromptChange,
  onGenerate,
  onRun,
  onClearOutput,
}: EditorToolbarProps) {
  return (
    <div className="space-y-3 rounded-xl border border-slate-700 bg-slate-900/80 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm text-slate-300">Language</label>
        <select
          value={language}
          onChange={(e) => onLanguageChange(e.target.value as EditorLanguage)}
          className="rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-100"
        >
          {LANGUAGES.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>

        <button
          type="button"
          onClick={onRun}
          disabled={isRunning}
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {isRunning ? 'Running…' : 'Run code'}
        </button>

        <button
          type="button"
          onClick={onClearOutput}
          className="rounded-md border border-slate-600 px-4 py-2 text-sm text-slate-200"
        >
          Clear output
        </button>
      </div>

      <div className="flex flex-col gap-2">
        <label className="text-sm text-slate-300">AI prompt</label>
        <div className="flex flex-col gap-2 md:flex-row">
          <input
            value={prompt}
            onChange={(e) => onPromptChange(e.target.value)}
            placeholder="Generate landing page with hero, pricing and CTA..."
            className="w-full rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-400"
          />
          <button
            type="button"
            onClick={onGenerate}
            disabled={isGenerating || !prompt.trim()}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
          >
            {isGenerating ? 'Generating…' : 'AI generate'}
          </button>
        </div>
      </div>
    </div>
  );
}
