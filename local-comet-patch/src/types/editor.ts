export type EditorLanguage =
  | 'html'
  | 'css'
  | 'javascript'
  | 'typescript'
  | 'json'
  | 'markdown'
  | 'python';

export interface RunCodeRequest {
  code: string;
  language: EditorLanguage;
}

export interface RunCodeResponse {
  stdout: string;
  stderr: string;
  previewHtml?: string;
}

export interface AIGenerateRequest {
  prompt: string;
  language: EditorLanguage;
  currentCode?: string;
}

export interface AIGenerateResponse {
  code: string;
}

export interface EditorState {
  code: string;
  language: EditorLanguage;
  isRunning: boolean;
  isGenerating: boolean;
  runResult: RunCodeResponse | null;
}
