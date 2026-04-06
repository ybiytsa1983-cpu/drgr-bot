/**
 * VM API client — connects local-comet frontend to DRGR VM server.
 *
 * All endpoints match vm/server.py routes.
 * Base URL defaults to http://localhost:5001 (DRGR_PORT).
 */
import type {
  AutomationStatus,
  BotActionResponse,
  BotStatusResponse,
  CaptchaSolveRequest,
  CaptchaSolveResponse,
  ChatRequest,
  ChatResponse,
  GenerateRequest,
  GenerateResponse,
  ModelsResponse,
  ResearchRequest,
  ResearchResponse,
  SettingsData,
  TaskRequest,
  TaskResponse,
  TgMessage,
  VmStatusResponse,
} from '../types/vm';

const VM_BASE = import.meta.env.VITE_VM_URL || 'http://localhost:5001';

// ---------------------------------------------------------------------------
//  Generic helpers
// ---------------------------------------------------------------------------

async function vmGet<T>(path: string): Promise<T> {
  const res = await fetch(`${VM_BASE}${path}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `GET ${path} → ${res.status}`);
  }
  return (await res.json()) as T;
}

async function vmPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${VM_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body != null ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `POST ${path} → ${res.status}`);
  }
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
//  Status / Health
// ---------------------------------------------------------------------------

export function getVmStatus(): Promise<VmStatusResponse> {
  return vmGet<VmStatusResponse>('/extension/report');
}

export function getHealth(): Promise<{ status: string }> {
  return vmGet<{ status: string }>('/health');
}

// ---------------------------------------------------------------------------
//  Models
// ---------------------------------------------------------------------------

export function getModels(): Promise<ModelsResponse> {
  return vmGet<ModelsResponse>('/models');
}

// ---------------------------------------------------------------------------
//  Chat
// ---------------------------------------------------------------------------

export function sendChat(payload: ChatRequest): Promise<ChatResponse> {
  return vmPost<ChatResponse>('/chat', payload);
}

// ---------------------------------------------------------------------------
//  Research / Article generator
// ---------------------------------------------------------------------------

export function runResearch(payload: ResearchRequest): Promise<ResearchResponse> {
  return vmPost<ResearchResponse>('/research', payload);
}

// ---------------------------------------------------------------------------
//  Text generation
// ---------------------------------------------------------------------------

export function generateText(payload: GenerateRequest): Promise<GenerateResponse> {
  return vmPost<GenerateResponse>('/generate', payload);
}

// ---------------------------------------------------------------------------
//  Bot management
// ---------------------------------------------------------------------------

export function getBotStatus(): Promise<BotStatusResponse> {
  return vmGet<BotStatusResponse>('/bot/status');
}

export function startBot(): Promise<BotActionResponse> {
  return vmPost<BotActionResponse>('/bot/start');
}

export function stopBot(): Promise<BotActionResponse> {
  return vmPost<BotActionResponse>('/bot/stop');
}

export function getBotLog(): Promise<{ log: string }> {
  return vmGet<{ log: string }>('/bot/log');
}

// ---------------------------------------------------------------------------
//  Settings (.env)
// ---------------------------------------------------------------------------

export function getSettings(): Promise<SettingsData> {
  return vmGet<SettingsData>('/settings');
}

export function saveSettings(data: SettingsData): Promise<{ ok: boolean }> {
  return vmPost<{ ok: boolean }>('/settings', data);
}

// ---------------------------------------------------------------------------
//  Automation
// ---------------------------------------------------------------------------

export function getAutomationStatus(): Promise<AutomationStatus> {
  return vmGet<AutomationStatus>('/api/automation/status');
}

export function getTasks(): Promise<TaskResponse[]> {
  return vmGet<TaskResponse[]>('/api/tasks');
}

export function createTask(payload: TaskRequest): Promise<TaskResponse> {
  return vmPost<TaskResponse>('/api/tasks', payload);
}

export function cancelTask(taskId: string): Promise<{ ok: boolean }> {
  return vmPost<{ ok: boolean }>(`/api/tasks/${taskId}/cancel`);
}

export function solveCaptcha(payload: CaptchaSolveRequest): Promise<CaptchaSolveResponse> {
  return vmPost<CaptchaSolveResponse>('/api/captcha/solve', payload);
}

// ---------------------------------------------------------------------------
//  Telegram messages
// ---------------------------------------------------------------------------

export function getTgMessages(): Promise<TgMessage[]> {
  return vmGet<TgMessage[]>('/chat/tg_messages');
}

export function sendTgMessage(text: string): Promise<{ ok: boolean }> {
  return vmPost<{ ok: boolean }>('/chat/tg_messages', { text });
}
