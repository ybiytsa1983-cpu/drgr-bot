import { useMemo, useState } from 'react';
import { CodeEditor } from '../components/CodeEditor';
import { EditorToolbar } from '../components/EditorToolbar';
import { PreviewFrame } from '../components/PreviewFrame';
import { ResultPanel } from '../components/ResultPanel';
import { generateCode, runCode } from '../lib/editorApi';
import type { EditorLanguage, RunCodeResponse } from '../types/editor';

const DEFAULT_CODE: Record<EditorLanguage, string> = {
  html: `<div class="p-6 font-sans">
  <h1 class="text-3xl font-bold">Hello from Editor</h1>
  <p>Edit and run to see live preview.</p>
</div>`,
  css: `body {\n  font-family: Inter, sans-serif;\n  margin: 0;\n  padding: 24px;\n}`,
  javascript: `console.log('Hello from JavaScript');`,
  typescript: `const message: string = 'Hello from TypeScript';\nconsole.log(message);`,
  json: `{"name":"local-comet","port":5051}`,
  markdown: `# Hello\n\nGenerated in EditorPage.`,
  python: `print('Hello from Python')`,
};

function fallbackPreview(language: EditorLanguage, code: string): string {
  if (language === 'html') return code;
  if (language === 'css') return `<style>${code}</style><div>CSS preview loaded</div>`;
  if (language === 'markdown') {
    return `<pre style="white-space: pre-wrap; font-family: sans-serif; padding: 16px;">${code
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')}</pre>`;
  }

  return `<pre style="white-space: pre-wrap; font-family: monospace; padding: 16px;">${code
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')}</pre>`;
}

export default function EditorPage() {
  const [language, setLanguage] = useState<EditorLanguage>('html');
  const [code, setCode] = useState<string>(DEFAULT_CODE.html);
  const [prompt, setPrompt] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [result, setResult] = useState<RunCodeResponse | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);

  const previewHtml = useMemo(() => {
    return result?.previewHtml ?? fallbackPreview(language, code);
  }, [result?.previewHtml, language, code]);

  const handleLanguageChange = (nextLanguage: EditorLanguage) => {
    setLanguage(nextLanguage);
    setCode(DEFAULT_CODE[nextLanguage]);
    setResult(null);
    setRequestError(null);
  };

  const handleRun = async () => {
    setIsRunning(true);
    setRequestError(null);

    try {
      const runResult = await runCode({ code, language });
      setResult(runResult);
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : 'Run request failed');
    } finally {
      setIsRunning(false);
    }
  };

  const handleGenerate = async () => {
    setIsGenerating(true);
    setRequestError(null);

    try {
      const generated = await generateCode({
        prompt,
        language,
        currentCode: code,
      });
      setCode(generated.code);
      setResult(null);
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : 'AI generation failed');
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <main className="mx-auto w-full max-w-[1600px] space-y-4 p-4 text-slate-100 lg:p-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">Editor</h1>
        <p className="text-sm text-slate-400">
          Monaco editor + code run + AI generation + live preview.
        </p>
      </header>

      <EditorToolbar
        language={language}
        prompt={prompt}
        isRunning={isRunning}
        isGenerating={isGenerating}
        onLanguageChange={handleLanguageChange}
        onPromptChange={setPrompt}
        onRun={handleRun}
        onGenerate={handleGenerate}
        onClearOutput={() => {
          setResult(null);
          setRequestError(null);
        }}
      />

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <CodeEditor code={code} language={language} onChange={setCode} />
        <PreviewFrame html={previewHtml} />
      </section>

      <ResultPanel result={result} error={requestError} />
    </main>
  );
}
