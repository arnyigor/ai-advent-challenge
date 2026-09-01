#!/usr/bin/env node
// server.mjs — нулевые зависимости. Статика + прокси к LLM со стримингом.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(__dirname, 'public');
const PORT = Number(process.env.PORT || 3000);

const key = (name) => process.env[name] || '';

async function detectLocal(url, timeout = 1200) {
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(timeout) });
    return r.ok;
  } catch { return false; }
}

// ---------- SSE-парсер (OpenAI-совместимый стрим) ----------
async function* sseStream(res, extract) {
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, idx).trim();
      buf = buf.slice(idx + 1);
      if (!line.startsWith('data:')) continue;
      const data = line.slice(5).trim();
      if (data === '[DONE]') return;
      try {
        const t = extract(JSON.parse(data));
        if (t) yield t;
      } catch { /* неполный/мусорный кадр — пропускаем */ }
    }
  }
}

async function* openaiStream(base, apiKey, model, messages) {
  const r = await fetch(base + '/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({ model, messages, stream: true }),
  });
  if (!r.ok) throw new Error(`${model}: HTTP ${r.status} ${(await r.text()).slice(0, 300)}`);
  yield* sseStream(r, (j) => j.choices?.[0]?.delta?.content || '');
}

function mockReply(prompt) {
  return (
    `Это MOCK-ответ (встроенный, без сети).\n\n` +
    `Вы спросили: «${prompt.slice(0, 200)}».\n\n` +
    `На этой машине не найдено ни локальной LLM, ни API-ключей,\n` +
    `поэтому я отвечаю сам, чтобы демо продолжало работать.\n\n` +
    `Чтобы получить ответ настоящей LLM:\n` +
    `  • запустите Ollama или llama.cpp локально, или\n` +
    `  • задайте DEEPSEEK_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY в окружении.`
  );
}

// ---------- Реестр бэкендов ----------
const BACKENDS = [
  {
    id: 'llama.cpp', label: 'llama.cpp', kind: 'local',
    url: process.env.LLAMACPP_URL || 'http://127.0.0.1:8080',
    defaultModel: 'qwen-27b',
    async detect() { return this.url ? detectLocal(this.url + '/health') : false; },
    async *stream({ messages, model }) {
      const r = await fetch(this.url + '/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: model || this.defaultModel, messages, stream: true }),
      });
      if (!r.ok) throw new Error(`llama.cpp: HTTP ${r.status} ${(await r.text()).slice(0, 300)}`);
      yield* sseStream(r, (j) => j.choices?.[0]?.delta?.content || '');
    },
  },
  {
    id: 'ollama', label: 'Ollama', kind: 'local',
    url: process.env.OLLAMA_URL || 'http://127.0.0.1:11434',
    defaultModel: 'llama3.2',
    async detect() { return this.url ? detectLocal(this.url + '/api/tags') : false; },
    async *stream({ messages, model }) {
      const r = await fetch(this.url + '/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: model || this.defaultModel, messages, stream: true }),
      });
      if (!r.ok) throw new Error(`Ollama: HTTP ${r.status} ${(await r.text()).slice(0, 300)}`);
      const text = await r.text();
      for (const line of text.split('\n')) {
        if (!line.trim()) continue;
        const j = JSON.parse(line);
        if (j.message?.content) yield j.message.content;
        if (j.done) {
          this._meta = { tokens: j.eval_count, time: +(j.eval_duration / 1e9).toFixed(2) };
        }
      }
    },
  },
  {
    id: 'deepseek', label: 'DeepSeek', kind: 'cloud',
    url: 'https://api.deepseek.com/v1',
    keyName: 'DEEPSEEK_API_KEY', defaultModel: 'deepseek-chat',
    async detect() { return !!key(this.keyName); },
    async *stream({ messages, model }) {
      yield* openaiStream(this.url, key(this.keyName), model || this.defaultModel, messages);
    },
  },
  {
    id: 'openai', label: 'OpenAI', kind: 'cloud',
    url: 'https://api.openai.com/v1',
    keyName: 'OPENAI_API_KEY', defaultModel: 'gpt-4o-mini',
    async detect() { return !!key(this.keyName); },
    async *stream({ messages, model }) {
      yield* openaiStream(this.url, key(this.keyName), model || this.defaultModel, messages);
    },
  },
  {
    id: 'routerai', label: 'RouterAI', kind: 'cloud',
    url: 'https://routerai.ru/api/v1',
    keyName: 'ROUTERAI_API_KEY', defaultModel: 'qwen/qwen3.8-27b',
    async detect() { return !!key(this.keyName); },
    async *stream({ messages, model }) {
      yield* openaiStream(this.url, key(this.keyName), model || this.defaultModel, messages);
    },
  },
  {
    id: 'gemini', label: 'Gemini', kind: 'cloud',
    url: 'https://generativelanguage.googleapis.com/v1beta',
    keyName: 'GEMINI_API_KEY', defaultModel: 'gemini-3.5-flash-lite',
    // fallback-цепочка (модели проверены по /models для этого ключа)
    fallbackModels: ['gemini-3.5-flash-lite', 'gemini-3.5-flash', 'gemini-3.6-flash', 'gemini-3.7-flash', 'gemini-2.5-flash'],
    async detect() {
      if (!key(this.keyName)) return false;
      // авто-детект актуальной модели (названия моделей меняются)
      try {
        const r = await fetch(`${this.url}/models?key=${key(this.keyName)}`, { signal: AbortSignal.timeout(15000) });
        if (r.ok) {
          const j = await r.json();
          const names = (j.models || []).map((m) => m.name);
          // приоритет — из проверенной цепочки, иначе любая flash
          const pick = this.fallbackModels.find((n) => names.includes('models/' + n) || names.includes(n))
            || names.find((n) => /flash/i.test(n) && !/tts|audio|image/i.test(n)) || names[0];
          if (pick) this.defaultModel = pick.replace(/^models\//, '');
        }
      } catch { /* оставляем defaultModel */ }
      return true;
    },
    async *stream({ messages, model }) {
      let m = model || this.defaultModel;
      if (!m.startsWith('models/')) m = 'models/' + m;
      const contents = messages.map((x) => ({
        role: x.role === 'assistant' ? 'model' : 'user',
        parts: [{ text: x.content }],
      }));
      const chain = this.fallbackModels || [m];
      const candidates = model ? [m, ...chain.filter((x) => x !== m)] : chain;
      let lastErr = null;
      for (const cm of candidates) {
        const r = await fetch(`${this.url}/models/${cm}:streamGenerateContent?alt=sse&key=${key(this.keyName)}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ contents }),
        });
        if (r.ok) {
          this.defaultModel = cm; // запоминаем рабочую модель
          yield* sseStream(r, (j) =>
            j.candidates?.[0]?.content?.parts?.map((p) => p.text || '').join('') || '');
          return;
        }
        lastErr = `Gemini [${cm}]: HTTP ${r.status} ${(await r.text()).slice(0, 200)}`;
      }
      throw new Error(lastErr || 'Gemini: все модели недоступны');
    },
  },
  {
    id: 'mock', label: 'Mock (без сети)', kind: 'mock',
    defaultModel: 'echo-1',
    async detect() { return true; },
    async *stream({ messages }) {
      const prompt = messages[messages.length - 1]?.content || '';
      const reply = mockReply(prompt);
      for (const word of reply.match(/[\s\S]{1,12}/g) || []) {
        yield word;
        await new Promise((r) => setTimeout(r, 15));
      }
    },
  },
];

const byId = (id) => BACKENDS.find((b) => b.id === id);

// ---------- HTTP ----------
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

function sendJSON(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(body);
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');

  // --- API: список бэкендов с доступностью (кэш 60 с — детект Gemini долгий) ---
  if (url.pathname === '/api/backends') {
    if (!globalThis.__backendsCache || Date.now() - globalThis.__backendsCache.t > 60000) {
      const list = await Promise.all(
        BACKENDS.map(async (b) => ({
          id: b.id, label: b.label, kind: b.kind,
          available: await b.detect(),
          defaultModel: b.defaultModel,
          url: b.kind === 'local' ? b.url : undefined,
        }))
      );
      globalThis.__backendsCache = { t: Date.now(), list };
    }
    const list = globalThis.__backendsCache.list;
    return sendJSON(res, 200, { backends: list });
  }

  // --- API: чат со стримингом (SSE) ---
  if (url.pathname === '/api/chat' && req.method === 'POST') {
    let raw = '';
    for await (const chunk of req) raw += chunk;
    let body;
    try { body = JSON.parse(raw); } catch { return sendJSON(res, 400, { error: 'bad json' }); }

    const backend = byId(body.backend) || byId('mock');
    const messages = Array.isArray(body.messages) && body.messages.length
      ? body.messages.map((m) => ({ role: m.role, content: String(m.content) }))
      : [{ role: 'user', content: String(body.prompt || 'Привет') }];

    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    });
    const send = (obj) => res.write(`data: ${JSON.stringify(obj)}\n\n`);

    const t0 = Date.now();
    let tokens = 0;
    try {
      for await (const text of backend.stream({ messages, model: body.model || undefined })) {
        tokens += text.length;
        send({ type: 'token', text });
      }
      const meta = { chars: tokens, time: +((Date.now() - t0) / 1000).toFixed(2), backend: backend.id };
      if (backend._meta) Object.assign(meta, backend._meta, { backend: backend.id });
      delete backend._meta;
      send({ type: 'done', meta });
    } catch (e) {
      send({ type: 'error', error: String(e.message || e) });
    }
    return res.end();
  }

  // --- Статика ---
  let file = url.pathname === '/' ? '/index.html' : url.pathname;
  try {
    const full = path.normalize(path.join(PUBLIC, file));
    if (!full.startsWith(PUBLIC)) { res.writeHead(403); return res.end(); }
    const data = await readFile(full);
    res.writeHead(200, { 'Content-Type': MIME[path.extname(full)] || 'application/octet-stream' });
    res.end(data);
  } catch {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('404 not found');
  }
});

server.listen(PORT, () => {
  console.log(`\n  ✦ llm-demo запущен:  http://localhost:${PORT}\n`);
  console.log('  Бэкенды проверяются при открытии страницы (/api/backends).\n');
});
