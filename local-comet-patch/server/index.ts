import cors from 'cors';
import dotenv from 'dotenv';
import express from 'express';
import vm from 'node:vm';

dotenv.config();

const app = express();
const PORT = Number(process.env.EDITOR_SERVER_PORT ?? 5052);

app.use(cors());
app.use(express.json({ limit: '2mb' }));

type EditorLanguage =
  | 'html'
  | 'css'
  | 'javascript'
  | 'typescript'
  | 'json'
  | 'markdown'
  | 'python';

function sanitize(text: string): string {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
}

app.post('/api/editor/run', (req, res) => {
  const code = String(req.body?.code ?? '');
  const language = String(req.body?.language ?? 'javascript') as EditorLanguage;

  let stdout = '';
  let stderr = '';
  let previewHtml = '';

  if (language === 'html') {
    previewHtml = code;
    return res.json({ stdout, stderr, previewHtml });
  }

  if (language === 'css') {
    previewHtml = `<style>${code}</style><div style="padding:12px;font-family:sans-serif;">CSS preview</div>`;
    return res.json({ stdout, stderr, previewHtml });
  }

  if (language === 'markdown') {
    previewHtml = `<pre style="white-space: pre-wrap; font-family: sans-serif; padding: 16px;">${sanitize(code)}</pre>`;
    return res.json({ stdout, stderr, previewHtml });
  }

  if (language === 'json') {
    try {
      const parsed = JSON.parse(code);
      stdout = JSON.stringify(parsed, null, 2);
    } catch (error) {
      stderr = error instanceof Error ? error.message : 'Invalid JSON';
    }
    previewHtml = `<pre style="white-space: pre-wrap; font-family: monospace; padding: 16px;">${sanitize(code)}</pre>`;
    return res.json({ stdout, stderr, previewHtml });
  }

  if (language === 'python') {
    stderr = 'Python execution is disabled in this lightweight Node server. Use external sandbox or Python worker.';
    previewHtml = `<pre style="white-space: pre-wrap; font-family: monospace; padding: 16px;">${sanitize(code)}</pre>`;
    return res.json({ stdout, stderr, previewHtml });
  }

  try {
    const logs: string[] = [];
    const sandbox = {
      console: {
        log: (...args: unknown[]) => logs.push(args.map((arg) => String(arg)).join(' ')),
      },
    };

    vm.createContext(sandbox);
    const script = new vm.Script(code);
    script.runInContext(sandbox, { timeout: 1000 });

    stdout = logs.join('\n');
  } catch (error) {
    stderr = error instanceof Error ? error.message : 'Runtime error';
  }

  previewHtml = `<pre style="white-space: pre-wrap; font-family: monospace; padding: 16px;">${sanitize(code)}</pre>`;
  return res.json({ stdout, stderr, previewHtml });
});

app.post('/api/editor/ai-generate', async (req, res) => {
  const prompt = String(req.body?.prompt ?? '').trim();
  const language = String(req.body?.language ?? 'html');
  const currentCode = String(req.body?.currentCode ?? '');

  if (!prompt) {
    return res.status(400).send('Prompt is required');
  }

  const aiBaseUrl = process.env.AI_BASE_URL;
  const aiApiKey = process.env.AI_API_KEY;
  const aiModel = process.env.AI_MODEL ?? 'gpt-4o-mini';

  if (!aiBaseUrl || !aiApiKey) {
    const fallback = `// AI env not configured\n// language: ${language}\n// prompt: ${prompt}\n${currentCode}`;
    return res.json({ code: fallback });
  }

  try {
    const response = await fetch(`${aiBaseUrl.replace(/\/$/, '')}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${aiApiKey}`,
      },
      body: JSON.stringify({
        model: aiModel,
        messages: [
          {
            role: 'system',
            content:
              'You generate code only. Return plain source code with no markdown fences or explanations.',
          },
          {
            role: 'user',
            content: `Language: ${language}\nPrompt: ${prompt}\nCurrent code:\n${currentCode}`,
          },
        ],
        temperature: 0.2,
      }),
    });

    if (!response.ok) {
      const text = await response.text();
      return res.status(response.status).send(text || 'AI request failed');
    }

    const data = (await response.json()) as {
      choices?: Array<{ message?: { content?: string } }>;
    };

    const code = data.choices?.[0]?.message?.content?.trim();
    if (!code) {
      return res.status(502).send('Empty AI response');
    }

    return res.json({ code });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'AI request failed';
    return res.status(500).send(message);
  }
});

app.get('/health', (_req, res) => {
  res.json({ ok: true });
});

app.listen(PORT, () => {
  console.log(`Editor server listening on http://localhost:${PORT}`);
});
