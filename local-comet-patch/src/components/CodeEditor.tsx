import Editor from '@monaco-editor/react';
import type { EditorLanguage } from '../types/editor';

interface CodeEditorProps {
  code: string;
  language: EditorLanguage;
  onChange: (value: string) => void;
}

export function CodeEditor({ code, language, onChange }: CodeEditorProps) {
  return (
    <div className="h-[520px] w-full overflow-hidden rounded-xl border border-slate-700 bg-slate-900">
      <Editor
        height="100%"
        language={language}
        value={code}
        onChange={(value) => onChange(value ?? '')}
        theme="vs-dark"
        options={{
          minimap: { enabled: false },
          fontSize: 14,
          lineNumbers: 'on',
          tabSize: 2,
          wordWrap: 'on',
          automaticLayout: true,
          scrollBeyondLastLine: false,
        }}
      />
    </div>
  );
}
