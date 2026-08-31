#!/usr/bin/env node
// cli.mjs — минимальный CLI: запрос в LLM через API, ответ в консоль.
// Использование:
//   node cli.mjs "привет"          # один вопрос (авто-детект бэкенда)
//   node cli.mjs                   # интерактивный режим
//   node cli.mjs --backend mock    # принудительный бэкенд
//   node cli.mjs --model qwen-27b "вопрос"
const args = process.argv.slice(2);
let backend = null, model = null;
const rest = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--backend') backend = args[++i];
  else if (args[i] === '--model') model = args[++i];
  else rest.push(args[i]);
}
const prompt = rest.join(' ') || null;

const key = (n) => process.env[n] || '';

const BACKENDS = {
  'llama.cpp': {
    url: process.env.LLAMACPP_URL || 'http://127.0.0.1:8080',
    chatPath: '/v1/chat/completions',
    defaultModel: 'qwen-27b',
    available: async () => ok(await fetch(this.url + '/health', { signal: AbortSignal.timeout(1000) })),
  },
  ollama: {
    url: process.env.OLLAMA_URL || 'http://127.0.0.1:11434',
    chatPath: '/api/chat',
    defaultModel: 'llama3.2',
    available: async () => ok(await fetch(this.url + '/api/tags', { signal: AbortSignal.timeout(1000) })),
  },
  deepseek: {
    url: 'https://api.deepseek.com/v1',
    chatPath: '/chat/completions',
    defaultModel: 'deepseek-chat',
    available: () => !!key('DEEPSEEK_API_KEY'),
  },
  openai: {
    url: 'https://api.openai.com/v1',
    chatPath: '/chat/completions',
    defaultModel: 'gpt-4o-mini',
    available: () => !!key('OPENAI_API_KEY'),
  },
  gemini: {
    url: 'https://generativelanguage.googleapis.com/v1beta',
    defaultModel: 'gemini-2.0-flash',
    available: () => !!key('GEMINI_API_KEY'),
  },
  mock: { available: () => true },
};

function ok(r) { return r && r.ok; }

async function pickBackend() {
  if (backend) {
    const b = BACKENDS[backend];
    if (!b) throw new Error('Неизвестный бэкенд: ' + backend + '. Есть: ' + Object.keys(BACKENDS).join(', '));
    return backend;
  }
  for (const id of ['llama.cpp', 'ollama', 'deepseek', 'openai', 'gemini']) {
    if (await BACKENDS[id].available()) return id;
  }
  console.error('⚠ Ничего не найдено (ни локальная LLM, ни API-ключи) → использую mock.');
  return 'mock';
}

async function ask(id, text) {
  const b = BACKENDS[id];
  if (id === 'mock') {
    console.log(`[mock] Это встроенный ответ без сети.\nВы спросили: «${text.slice(0, 150)}»\nЗапустите Ollama/llama.cpp или задайте DEEPSEEK_API_KEY для настоящей LLM.`);
    return;
  }
  const t0 = Date.now();
  if (id === 'gemini') {
    const m = model || b.defaultModel;
    const r = await fetch(`${b.url}/models/${m}:generateContent?key=${key('GEMINI_API_KEY')}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contents: [{ parts: [{ text }] }] }),
    });
    if (!r.ok) throw new Error(`Gemini HTTP ${r.status}: ${(await r.text()).slice(0, 300)}`);
    const j = await r.json();
    console.log(j.candidates?.[0]?.content?.parts?.map((p) => p.text).join('') || '(пусто)');
  } else {
    const m = model || b.defaultModel;
    const headers = { 'Content-Type': 'application/json' };
    const apiKey = key(id === 'deepseek' ? 'DEEPSEEK_API_KEY' : 'OPENAI_API_KEY');
    if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
    const url = b.url + b.chatPath;
    const body = id === 'ollama'
      ? { model: m, messages: [{ role: 'user', content: text }] }
      : { model: m, messages: [{ role: 'user', content: text }] };
    const r = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(`${id} HTTP ${r.status}: ${(await r.text()).slice(0, 300)}`);
    const j = await r.json();
    console.log(j.choices?.[0]?.message?.content ?? j.message?.content ?? JSON.stringify(j).slice(0, 500));
  }
  console.error(`\n— ${id} · ${((Date.now() - t0) / 1000).toFixed(1)} c`);
}

async function main() {
  const id = await pickBackend();
  if (prompt !== null) {
    await ask(id, prompt);
    return;
  }
  // интерактивный режим
  console.log(`✦ LLM demo CLI · бэкенд: ${id} · введите /exit для выхода\n`);
  const { createInterface } = await import('node:readline');
  const iface = createInterface({ input: process.stdin, output: process.stdout });
  const q = () => new Promise((res) => iface.question('вы> ', res));
  while (true) {
    const line = (await q()).trim();
    if (!line) continue;
    if (line === '/exit' || line === '/quit') break;
    try { await ask(id, line); } catch (e) { console.error('Ошибка: ' + e.message); }
    console.log();
  }
  iface.close();
}

main().catch((e) => { console.error('Ошибка: ' + e.message); process.exit(1); });
