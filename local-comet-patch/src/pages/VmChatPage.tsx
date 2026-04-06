import { useCallback, useRef, useState } from 'react';
import { getModels, sendChat } from '../lib/vmApi';
import type { ChatMessage, ModelsResponse } from '../types/vm';

export default function VmChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [model, setModel] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Fetch models once on mount
  const modelsLoaded = useRef(false);
  if (!modelsLoaded.current) {
    modelsLoaded.current = true;
    getModels()
      .then((res: ModelsResponse) => {
        const all = [...res.ollama, ...res.lmstudio];
        setModels(all);
        if (all.length > 0) setModel(all[0]);
      })
      .catch(() => {});
  }

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: ChatMessage = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const res = await sendChat({
        message: text,
        model: model || undefined,
        history: messages,
      });
      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: res.reply || res.error || 'Нет ответа',
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      const errMsg: ChatMessage = {
        role: 'assistant',
        content: `Ошибка: ${err instanceof Error ? err.message : 'Запрос не выполнен'}`,
      };
      setMessages((prev) => [...prev, errMsg]);
    } finally {
      setLoading(false);
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [input, loading, model, messages]);

  return (
    <main className="mx-auto flex h-[calc(100vh-60px)] w-full max-w-[900px] flex-col p-4 text-slate-100 lg:p-6">
      <header className="mb-4 space-y-1">
        <h1 className="text-2xl font-bold">💬 Чат с AI</h1>
        <p className="text-sm text-slate-400">
          Общайтесь с Ollama / LM Studio через VM сервер
        </p>
      </header>

      {/* Model selector */}
      {models.length > 0 ? (
        <div className="mb-3 flex items-center gap-2">
          <label className="text-xs text-slate-400">Модель:</label>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="rounded-md border border-slate-600 bg-slate-800 px-2 py-1 text-xs text-slate-200"
          >
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {/* Messages */}
      <div className="flex-1 space-y-3 overflow-y-auto rounded-xl border border-slate-700 bg-slate-900/80 p-4">
        {messages.length === 0 ? (
          <p className="text-center text-sm text-slate-500">
            Напишите сообщение чтобы начать диалог
          </p>
        ) : null}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`rounded-lg p-3 text-sm ${
              msg.role === 'user'
                ? 'ml-8 bg-indigo-900/50 text-indigo-100'
                : 'mr-8 bg-slate-800 text-slate-200'
            }`}
          >
            <div className="mb-1 text-xs font-medium text-slate-400">
              {msg.role === 'user' ? '👤 Вы' : '🤖 AI'}
            </div>
            <div className="whitespace-pre-wrap">{msg.content}</div>
          </div>
        ))}
        {loading ? (
          <div className="mr-8 rounded-lg bg-slate-800 p-3 text-sm text-slate-400">
            ⏳ Думаю…
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="mt-3 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          placeholder="Введите сообщение…"
          className="flex-1 rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
        />
        <button
          type="button"
          onClick={handleSend}
          disabled={loading || !input.trim()}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          ➤
        </button>
      </div>
    </main>
  );
}
