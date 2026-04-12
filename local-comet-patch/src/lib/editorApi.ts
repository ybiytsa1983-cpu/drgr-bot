import type {
  AIGenerateRequest,
  AIGenerateResponse,
  RunCodeRequest,
  RunCodeResponse,
} from '../types/editor';

const API_BASE = import.meta.env.VITE_EDITOR_API_URL || 'http://localhost:5052';

async function request<TResponse>(path: string, body: unknown): Promise<TResponse> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }

  return (await response.json()) as TResponse;
}

export function runCode(payload: RunCodeRequest): Promise<RunCodeResponse> {
  return request<RunCodeResponse>('/api/editor/run', payload);
}

export function generateCode(payload: AIGenerateRequest): Promise<AIGenerateResponse> {
  return request<AIGenerateResponse>('/api/editor/ai-generate', payload);
}
