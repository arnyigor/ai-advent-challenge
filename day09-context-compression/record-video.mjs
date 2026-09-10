#!/usr/bin/env node
// Records a concise UI walkthrough using the already completed real A/B run.
import {spawn, spawnSync} from 'node:child_process';
import {mkdirSync, mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const dayDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(dayDir, '..');
const result = JSON.parse(readFileSync(path.join(dayDir, 'results', 'comparison.json'), 'utf8'));
const framesDir = mkdtempSync(path.join(os.tmpdir(), 'day09-video-frames-'));
const userDataDir = mkdtempSync(path.join(os.tmpdir(), 'day09-video-chrome-'));
const port = Number(process.env.DAY09_WEB_PORT || 8009);
const cdpPort = Number(process.env.DAY09_CDP_PORT || 9269);
const chromePath = process.env.CHROME_PATH || path.join(process.env.ProgramFiles || '', 'Google', 'Chrome', 'Application', 'chrome.exe');
const ffmpegPath = process.env.FFMPEG_PATH || 'ffmpeg';
const pythonPath = process.env.PYTHON_PATH || 'python';
const output = process.argv.includes('--out')
  ? path.resolve(process.argv[process.argv.indexOf('--out') + 1])
  : path.resolve(rootDir, 'ChallengeVideos', 'day09-demo.mp4');
mkdirSync(path.dirname(output), {recursive: true});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const server = spawn(pythonPath, ['web_server.py', '--port', String(port)], {cwd: dayDir, stdio: 'ignore'});
const chrome = spawn(chromePath, [
  '--headless=new', `--remote-debugging-port=${cdpPort}`, '--no-sandbox',
  `--user-data-dir=${userDataDir}`, '--disable-gpu', '--window-size=1440,1000',
  '--hide-scrollbars', 'about:blank',
], {stdio: 'ignore'});

async function waitJson(url, attempts = 80) {
  for (let index = 0; index < attempts; index++) {
    try { const response = await fetch(url); if (response.ok) return response.json(); } catch {}
    await sleep(250);
  }
  throw new Error(`Не дождался ${url}`);
}

let socket;
let callId = 0;
const pending = new Map();
function cdp(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++callId;
    pending.set(id, {resolve, reject});
    socket.send(JSON.stringify({id, method, params}));
  });
}
const evaluate = (expression) => cdp('Runtime.evaluate', {expression, returnByValue: true}).then((value) => {
  if (value.exceptionDetails) throw new Error(value.exceptionDetails.text);
  return value.result.value;
});

let recording = true;
let frame = 0;
async function camera() {
  while (recording) {
    const {data} = await cdp('Page.captureScreenshot', {format: 'png', optimizeForSpeed: true});
    writeFileSync(path.join(framesDir, `f${String(frame++).padStart(5, '0')}.png`), Buffer.from(data, 'base64'));
    await sleep(125);
  }
}

const captionScript = (caption) => `(() => {
  let bar = document.getElementById('videoCaption');
  if (!bar) {
    bar = document.createElement('div'); bar.id = 'videoCaption';
    bar.style.cssText = 'position:fixed;left:0;right:320px;top:73px;z-index:9999;background:#030712f2;color:#f5d76e;border-bottom:1px solid #334155;padding:12px;text-align:center;font:700 16px Segoe UI';
    document.body.appendChild(bar);
    const transcript = document.getElementById('msgsInner');
    if (transcript) transcript.style.paddingTop = '68px';
  }
  bar.textContent = ${JSON.stringify(caption)};
})()`;

async function scene(caption, action = null, duration = 4200) {
  if (action) await evaluate(action);
  await evaluate(captionScript(caption));
  await sleep(duration);
}

// Реальный transcript прогона: сообщения длинные, и это объясняет счёт токенов.
const dumpScript = `
import json, sqlite3, sys
rows = sqlite3.connect(sys.argv[1]).execute(
    "select role, content from messages where session_id = ? order by rowid", (sys.argv[2],)
).fetchall()
print(json.dumps([{"role": role, "content": content} for role, content in rows], ensure_ascii=False))
`;
const dumped = spawnSync(pythonPath, ['-c', dumpScript, path.join(dayDir, 'comparison.db'), 'day09-compressed'], {
  encoding: 'utf8', env: {...process.env, PYTHONIOENCODING: 'utf-8'},
});
if (dumped.status !== 0) throw new Error(`Не смог прочитать transcript: ${dumped.stderr}`);
const transcript = JSON.parse(dumped.stdout);

const helpersScript = `(() => {
  const inner = document.getElementById('msgsInner');
  inner.innerHTML = '';
  const set = (id, value) => { const node = document.getElementById(id); if (node) node.textContent = String(value); };
  window.__demo = {
    push(role, text) {
      const node = document.createElement('div');
      node.className = 'msg ' + role;
      node.innerHTML = '<div class="bubble"></div>';
      const bubble = node.firstChild;
      bubble.textContent = text;
      // Длинные сообщения показываем срезанными, но с честной длиной.
      if (text.length > 400) {
        bubble.style.cssText = 'max-height:180px;overflow:hidden;position:relative';
        const badge = document.createElement('div');
        badge.textContent = text.length.toLocaleString('ru-RU') + ' символов в этом сообщении';
        badge.style.cssText = 'font:600 12px Segoe UI;color:#f5d76e;margin-top:4px';
        node.appendChild(badge);
      }
      inner.appendChild(node);
      const box = document.getElementById('msgs');
      box.scrollTop = box.scrollHeight;
    },
    metrics(values) { for (const [id, value] of Object.entries(values)) set(id, value); }
  };
})()`;

// Один ход диалога: сообщение пользователя, ответ агента и обновлённые метрики.
function turnScript(user, assistant, metrics) {
  return `(() => {
    window.__demo.push('user', ${JSON.stringify(user)});
    window.__demo.push('assistant', ${JSON.stringify(assistant)});
    window.__demo.metrics(${JSON.stringify(metrics)});
  })()`;
}

async function main() {
  await waitJson(`http://127.0.0.1:${port}/api/config`);
  const targets = await waitJson(`http://127.0.0.1:${cdpPort}/json`);
  socket = new WebSocket(targets.find((target) => target.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve) => { socket.onopen = resolve; });
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const callbacks = pending.get(message.id); pending.delete(message.id);
    message.error ? callbacks.reject(new Error(message.error.message)) : callbacks.resolve(message.result);
  };
  await cdp('Page.enable');
  await cdp('Runtime.enable');
  await cdp('Page.navigate', {url: `http://127.0.0.1:${port}/`});
  await sleep(1800);
  await evaluate(helpersScript);
  await evaluate(captionScript('День 9 · Диалог начинается с нуля: пока история короткая, модель получает её целиком'));
  const cameraPromise = camera();
  await sleep(3200);

  const compressed = result.modes.compressed;
  const summary = compressed.final_summary.content;
  const growth = compressed.setup_turns.map((turn) => turn.request_tokens_estimate);
  // Токены истории — локальная оценка, поэтому «≈», как в самом UI.
  const approx = (value) => `≈${value.toLocaleString('ru-RU')}`;
  const session = {input: 0, output: 0, calls: 0};
  const account = (usage) => {
    session.input += usage.input_tokens;
    session.output += usage.output_tokens;
    session.calls += 1;
    return {
      sessInput: session.input.toLocaleString('ru-RU'),
      sessOutput: session.output.toLocaleString('ru-RU'),
      sessTotal: (session.input + session.output).toLocaleString('ru-RU'),
      sessCalls: String(session.calls),
    };
  };
  const setupTurnCount = compressed.setup_turns.length;
  const setup = Array.from({length: setupTurnCount}, (_, index) => [
    transcript[index * 2].content, transcript[index * 2 + 1].content,
  ]);
  const captions = [
    'Ход 1 — факт для финальной проверки: код проекта. Каждое сообщение ≈1 400 символов',
    'Ход 2 — второй факт: город. Сообщения намеренно объёмные, чтобы история дорожала',
    'Ход 3 — третий факт: бюджет',
    'Ход 4 — четвёртый факт: формат отчёта',
    'Ходы 5–8 — нейтральный фон: история растёт, контекст LLM растёт вместе с ней',
    'Полная история = контекст LLM. Каждый запрос дороже предыдущего',
    'Порог близко: последние 6 сообщений останутся дословно, старые уйдут в пакет из 10',
    'Накопились 16 сообщений — из них ровно 10 старых готовы к сжатию',
  ];
  for (let index = 0; index < setup.length; index++) {
    const tokens = growth[index];
    await scene(captions[index], turnScript(setup[index][0], setup[index][1], {
      fullTokens: approx(tokens),
      effectiveTokens: approx(tokens),
      savedTokens: '≈0',
      summarizedCount: '0',
      verbatimCount: String((index + 1) * 2),
      summaryRevision: '0',
      ...account(compressed.setup_turns[index].usage),
    }), index < 4 ? 2600 : 1900);
  }

  const first = compressed.probes[0].compression;
  const summaryCall = first.summary_calls_this_turn[0];
  const compressionMetrics = {
    summarizedCount: String(first.summarized_message_count),
    verbatimCount: String(first.verbatim_message_count),
    summaryRevision: String(first.summary_revision),
    summaryText: summary,
    fullTokens: approx(first.full_history_tokens.value),
    effectiveTokens: approx(first.effective_history_tokens.value),
    savedTokens: approx(first.estimated_tokens_saved_this_request),
    ...account(summaryCall.usage),
  };
  await scene(`Срабатывает сжатие: отдельный вызов модели превращает 10 старых сообщений в одну сводку (+${summaryCall.usage.total_tokens} токенов разово)`, `(() => {
    window.__demo.metrics(${JSON.stringify(compressionMetrics)});
    document.getElementById('summaryText').scrollIntoView({block: 'center'});
  })()`, 6000);
  await scene(`Контекст LLM упал с ${first.full_history_tokens.value} до ${first.effective_history_tokens.value} токенов — при том, что полный диалог никуда не делся`, null, 5200);

  const probeCaptions = [
    'Проверка: спрашиваем про факт из первого сообщения — оно уже сжато',
    'Второй факт — тоже только из сводки',
    'Третий факт — бюджет',
    'Четвёртый факт — формат отчёта',
  ];
  for (let index = 0; index < compressed.probes.length; index++) {
    const probe = compressed.probes[index];
    await scene(probeCaptions[index], turnScript(probe.question, probe.answer, {
      fullTokens: approx(probe.compression.full_history_tokens.value),
      effectiveTokens: approx(probe.compression.effective_history_tokens.value),
      savedTokens: approx(probe.compression.estimated_tokens_saved_this_request),
      summarizedCount: String(probe.compression.summarized_message_count),
      verbatimCount: String(probe.compression.verbatim_message_count),
      ...account(probe.usage),
    }), index === 0 ? 4600 : 2800);
  }

  if (session.input !== compressed.total_input_tokens || session.calls !== compressed.api_calls) {
    throw new Error(`Метрики сессии разошлись с прогоном: ${session.input}/${session.calls}`);
  }
  await scene('Все четыре факта восстановлены из сводки — качество не просело', null, 4600);
  await scene('Тот же диалог прогнан и без сжатия — честный A/B на одном провайдере и одной модели', "document.getElementById('comparison').scrollIntoView({block:'center'})", 5000);
  await scene(`Качество: ${result.modes.full_history.quality_score}% → ${result.modes.compressed.quality_score}%. Вход: ${result.modes.full_history.total_input_tokens} → ${result.modes.compressed.total_input_tokens} токенов`, null, 6000);
  await scene(`Сэкономлено ${result.comparison.input_tokens_saved} входных токенов (${result.comparison.input_token_saving_percent}%)`, null, 5000);
  await scene('Код: context_manager.py · agent.py · history_store.py · run_comparison.py', null, 4600);

  recording = false;
  await cameraPromise;
  const captureFps = 8;
  const encoded = spawnSync(ffmpegPath, [
    '-y', '-framerate', String(captureFps), '-i', path.join(framesDir, 'f%05d.png'),
    '-vf', 'fps=24,scale=trunc(iw/2)*2:trunc(ih/2)*2', '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p', '-crf', '23', output,
  ], {stdio: 'inherit'});
  if (encoded.status !== 0) throw new Error('ffmpeg завершился с ошибкой');
  console.log(`Видео: ${output}`);
}

try {
  await main();
} finally {
  recording = false;
  try { socket?.close(); } catch {}
  try { chrome.kill(); } catch {}
  try { server.kill(); } catch {}
}
