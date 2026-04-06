/** Types for DRGR VM server integration. */

export interface VmHealthData {
  ollama: { available: boolean; url: string; models: string[] };
  lmstudio: { available: boolean; url: string; models: string[] };
  bot: { running: boolean; pid: number | null };
  env_exists: boolean;
  bot_script_exists: boolean;
  uptime: number;
}

export interface VmStatusResponse {
  status: string;
  data: VmHealthData;
  report?: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface ChatRequest {
  message: string;
  model?: string;
  history?: ChatMessage[];
}

export interface ChatResponse {
  reply: string;
  model?: string;
  error?: string;
}

export interface ResearchRequest {
  query: string;
  max_sources?: number;
}

export interface ResearchResponse {
  article: string;
  sources: Array<{ title: string; url: string }>;
  error?: string;
}

export interface GenerateRequest {
  prompt: string;
  model?: string;
  max_tokens?: number;
}

export interface GenerateResponse {
  text: string;
  model?: string;
  error?: string;
}

export interface BotStatusResponse {
  running: boolean;
  pid: number | null;
}

export interface BotActionResponse {
  ok: boolean;
  message: string;
}

export interface SettingsData {
  [key: string]: string;
}

export interface ModelsResponse {
  ollama: string[];
  lmstudio: string[];
}

export interface AutomationStatus {
  selenium_available: boolean;
  twocaptcha_available: boolean;
  llm_available: boolean;
  ollama_url: string;
  lmstudio_url: string;
  active_tasks: number;
}

export interface TaskRequest {
  task_type: string;
  url?: string;
  login_url?: string;
  username?: string;
  password?: string;
  site_key?: string;
  cycles?: number;
}

export interface TaskResponse {
  id: string;
  status: string;
  result?: string;
  error?: string;
}

export interface CaptchaSolveRequest {
  method?: 'auto' | 'click' | 'stealth' | '2captcha';
  page_url: string;
  site_key?: string;
}

export interface CaptchaSolveResponse {
  success: boolean;
  method_used?: string;
  token?: string;
  error?: string;
}

export interface TgMessage {
  id: number;
  text: string;
  from?: string;
  date?: string;
}
