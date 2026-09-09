#!/usr/bin/env node
// Records ChallengeVideos/day08-demo.mp4 by driving the real web UI against
// the real DeepSeek API (headless Chrome + CDP screenshots + ffmpeg, same
// technique as Day 7). See VIDEO_SCRIPT.md for the scene-by-scene plan and
// the real numbers this run is expected to reproduce.
import {spawn, spawnSync} from 'node:child_process';
import {mkdirSync, mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const dayDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(dayDir, '..');
const framesDir = path.resolve(dayDir, 'video-frames');
if (!framesDir.startsWith(dayDir + path.sep)) throw new Error('Некорректная папка кадров');
rmSync(framesDir, {recursive: true, force: true});
mkdirSync(framesDir, {recursive: true});

const port = Number(process.env.DAY08_WEB_PORT || 8008);
const pageUrl = `http://127.0.0.1:${port}/`;
const dbPath = path.join(dayDir, 'chat_history.db');
const chromePath = process.env.CHROME_PATH || path.join(process.env.ProgramFiles || '', 'Google', 'Chrome', 'Application', 'chrome.exe');
const ffmpegPath = process.env.FFMPEG_PATH || 'ffmpeg';
const cdpPort = Number(process.env.DAY08_CDP_PORT || 9268);
const pythonPath = process.env.PYTHON_PATH || 'python';
const userDataDir = mkdtempSync(path.join(os.tmpdir(), 'day08-video-chrome-'));
const output = process.argv.includes('--out')
  ? path.resolve(process.argv[process.argv.indexOf('--out') + 1])
  : path.resolve(rootDir, 'ChallengeVideos', 'day08-demo.mp4');
mkdirSync(path.dirname(output), {recursive: true});

// A fresh session (both the server-side DB and the browser profile, so
// localStorage's random session id doesn't survive from a previous take).
rmSync(dbPath, {force: true});

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function waitJson(url, attempts = 60) {
  for (let i = 0; i < attempts; i++) {
    try { const response = await fetch(url); if (response.ok) return response.json(); } catch {}
    await sleep(250);
  }
  throw new Error(`Не дождался ${url}`);
}

function startServer() {
  return spawn(pythonPath, ['web_server.py', '--port', String(port)], {cwd: dayDir, stdio: 'ignore'});
}

const server = startServer();
const chrome = spawn(chromePath, [
  '--headless=new', `--remote-debugging-port=${cdpPort}`, '--no-sandbox',
  `--user-data-dir=${userDataDir}`,
  '--disable-gpu', '--window-size=1440,1000', '--hide-scrollbars', 'about:blank',
], {stdio: 'ignore'});

let socket, callId = 0;
const pending = new Map();
function cdp(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++callId; pending.set(id, {resolve, reject});
    socket.send(JSON.stringify({id, method, params}));
  });
}
const evaluate = expression => cdp('Runtime.evaluate', {expression, returnByValue: true, timeout: 20000}).then(x => {
  if (x.exceptionDetails) throw new Error(x.exceptionDetails.text);
  return x.result.value;
});

let recording = true, index = 0, captureStartedAt = 0;
async function camera() {
  captureStartedAt = Date.now();
  while (recording) {
    const {data} = await cdp('Page.captureScreenshot', {format: 'png', optimizeForSpeed: true});
    writeFileSync(path.join(framesDir, `f${String(index++).padStart(5, '0')}.png`), Buffer.from(data, 'base64'));
    await sleep(100);
  }
}

const captionScript = caption => `(() => {
  let bar=document.getElementById('videoCaption');
  if(!bar){bar=document.createElement('div');bar.id='videoCaption';bar.style.cssText='position:fixed;left:0;right:0;bottom:0;z-index:9999;background:#02070bea;color:#ffdf70;border-top:1px solid #345;padding:11px;text-align:center;font:700 15px Segoe UI';document.body.appendChild(bar)}
  bar.textContent=${JSON.stringify(caption)};
})()`;

async function scene(caption, action, duration = 4000) {
  if (action) await evaluate(action);
  await evaluate(captionScript(caption));
  await sleep(duration);
}

async function waitFor(expression, attempts = 400) {
  for (let i = 0; i < attempts; i++) {
    if (await evaluate(expression)) return true;
    await sleep(250);
  }
  return false;
}

const sendMessageScript = text => `(() => {
  const ta=document.getElementById('prompt');
  ta.value=${JSON.stringify(text)};
  ta.dispatchEvent(new Event('input'));
  document.getElementById('form').requestSubmit();
})()`;

// Waits until the send resolves as either a normal bot reply (.md bubble) or
// an error bubble (.msg.err — local/provider context-limit or any other
// failure). Returns which one happened; never fabricates an outcome.
async function waitForOutcome(label, attempts = 500) {
  const before = await evaluate(
    "[document.querySelectorAll('.turn:not(.me) .md').length, document.querySelectorAll('.msg.err').length]"
  );
  for (let i = 0; i < attempts; i++) {
    const [ok, err] = await evaluate(
      "[document.querySelectorAll('.turn:not(.me) .md').length, document.querySelectorAll('.msg.err').length]"
    );
    if (ok > before[0]) return 'ok';
    if (err > before[1]) return 'err';
    await sleep(250);
  }
  throw new Error(`${label}: ответ не пришёл за отведённое время — запись остановлена, а не подделана`);
}

async function lastErrorText() {
  return evaluate("(() => { const n=document.querySelectorAll('.msg.err'); return n[n.length-1]?.firstChild?.textContent || ''; })()");
}

async function readMetric(id) {
  return evaluate(`document.getElementById(${JSON.stringify(id)}).textContent`);
}

// The right-hand agent panel is independently scrollable (.panel {overflow-y:
// auto}); the metric cards, session totals and growth table/chart all sit
// below the fold at the default scroll position, so they need an explicit
// scroll to ever appear on camera.
async function scrollPanelTo(elementId) {
  await evaluate(`document.getElementById(${JSON.stringify(elementId)}).scrollIntoView({block:'center'})`);
}
async function scrollPanelToTop() {
  await evaluate("document.querySelector('.panel').scrollTo({top:0})");
}

// --- Content generators (mirrors run_scenarios.py's vocabulary/approach in
// JS so the video reproduces the same kind of real content, not a replay).
function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const VOCAB = (
  'карта маршрут отчёт датчик канал журнал архив сектор модуль реестр '
  + 'буфер индекс пакет узел процесс история событие сигнал статус команда '
  + 'запрос ответ система сессия модель контекст данные параметр значение '
  + 'таблица очередь ключ ссылка адрес блок кадр слой уровень граница'
).split(' ');
function generateBlock(seedIndex, wordCount) {
  const rnd = mulberry32(1000 + seedIndex);
  const words = [];
  for (let i = 0; i < wordCount; i++) words.push(VOCAB[Math.floor(rnd() * VOCAB.length)]);
  return `Блок ${seedIndex}. ${words.join(' ')}. Подтверди получение одной короткой фразой.`;
}
const generateSymbolWall = charCount => '!'.repeat(charCount);

const FACT = 'Запомни: код проекта — Маяк-17. Ответь кратко.';
const RECALL = 'Какой код проекта я назвал? Ответь одной строкой.';

async function send(text, label) {
  await evaluate(sendMessageScript(text));
  return waitForOutcome(label);
}

async function clearContext() {
  await evaluate("document.getElementById('clearContextBtn').click()");
  await sleep(1200);
}

async function main() {
  await waitJson(`http://127.0.0.1:${port}/api/config`);
  const targets = await waitJson(`http://127.0.0.1:${cdpPort}/json`);
  socket = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise(resolve => { socket.onopen = resolve; });
  socket.onmessage = event => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id); pending.delete(msg.id);
      msg.error ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result);
    }
  };
  await cdp('Page.enable'); await cdp('Runtime.enable');
  await cdp('Page.navigate', {url: pageUrl});
  await waitFor("document.getElementById('providerSelect')!==null && providerSelect.options.length>1");
  await waitFor("document.querySelector('#providerSelect option[value=\\\"deepseek\\\"]')!==null");
  const cameraPromise = camera();

  await scene('Day 08 · Работа с токенами — карточки метрик, таблица и график роста расхода по ходам', null, 4000);

  await evaluate("(() => { providerSelect.value='deepseek'; providerSelect.dispatchEvent(new Event('change')); })()");
  await scene('Фиксируем провайдера: DeepSeek deepseek-v4-flash, окно 1 000 000 токенов', null, 3500);

  // --- Scene A: short dialogue ---
  await scene('Сценарий A — короткий диалог', null, 2000);
  if (await send(FACT, 'A.1 факт') !== 'ok') throw new Error('A.1: ожидался успешный ответ');
  await scene('Новое сообщение — пара слов; вход API уже включает system prompt агента', null, 4000);
  if (await send(RECALL, 'A.2 вопрос о факте') !== 'ok') throw new Error('A.2: ожидался успешный ответ');
  const aRequest = await readMetric('metricRequest');
  await scene(`Агент вспомнил «Маяк-17» из истории. Вход API этого хода: ${aRequest}`, null, 5000);

  await scrollPanelTo('metricCurrent');
  await scene('Панель агента: метрики последнего хода и накопленная статистика сессии', null, 4500);
  await scrollPanelToTop();

  await clearContext();
  await scene('Очистили контекст — новая пустая сессия для сценария B', null, 2500);

  // --- Scene B: long dialogue ---
  if (await send(FACT, 'B.1 факт') !== 'ok') throw new Error('B.1: ожидался успешный ответ');
  await scene('Сценарий B — тот же факт, затем несколько разных смысловых блоков подряд', null, 3000);
  for (let i = 1; i <= 5; i++) {
    const block = generateBlock(i, 400);
    if (await send(block, `B blok ${i}`) !== 'ok') throw new Error(`B блок ${i}: ожидался успешный ответ`);
    if (i <= 2) {
      const req = await readMetric('metricRequest');
      await scene(`Блок ${i} принят. Вход API вырос до ${req} — история снова уходит в запрос целиком`, null, 3000);
    }
  }
  await scene('Ходы 3–5 отправлены так же, без пауз — видно по таблице и графику справа', null, 3000);
  if (await send(RECALL, 'B.recall') !== 'ok') throw new Error('B.recall: ожидался успешный ответ');
  const bRequest = await readMetric('metricRequest');
  await scene(`Тот же короткий вопрос — вход API теперь ${bRequest}: одна и та же реплика стоит на порядок дороже`, null, 6000);

  await scrollPanelTo('usageChart');
  await scene('Таблица и график роста по ходам — вход растёт с каждым сообщением, накопленный расход ещё быстрее', null, 5500);
  await scrollPanelToTop();

  await clearContext();
  await scene('Очистили контекст — сценарий C: настоящее переполнение', null, 2500);

  // --- Scene C: overflow ---
  if (await send(FACT, 'C.1 факт') !== 'ok') throw new Error('C.1: ожидался успешный ответ');
  if (await send('Подтверди получение одной короткой фразой.', 'C.2 warmup') !== 'ok') {
    throw new Error('C.2: ожидался успешный ответ');
  }
  await scene('Немного истории для затравки. Теперь — стена из 999 999 символов "!"', null, 3000);

  const wall = generateSymbolWall(999_999);
  const wallOutcome = await send(wall, 'C.3 стена символов (локальный отказ)');
  if (wallOutcome !== 'err') throw new Error('C.3: ожидался локальный отказ, а не успешный ответ');
  const wallError = await lastErrorText();
  await scene(`Локальная оценка — по токену на символ — сама превысила 1 000 000: «${wallError}». Запрос к API не ушёл`, null, 6000);

  await evaluate("(() => { const cb=document.getElementById('forceOverflowApi'); cb.checked=true; cb.dispatchEvent(new Event('change')); })()");
  await scene('Включаем «Эксперимент: отправить в API даже при локальном превышении» и повторяем ту же стену', null, 2500);
  const forcedOutcome = await send(wall, 'C.4 та же стена с force');
  if (forcedOutcome !== 'ok') throw new Error('C.4: ожидался успешный ответ (настоящий токенизатор сжимает повторы)');
  const forcedInput = await readMetric('sessInput');
  await scene(`Настоящий токенизатор DeepSeek сжал повторы символов — запрос прошёл. Реальный вход сессии: ${forcedInput} токенов, а не ≈1 000 000`, null, 6000);
  await evaluate("(() => { const cb=document.getElementById('forceOverflowApi'); cb.checked=false; cb.dispatchEvent(new Event('change')); })()");

  // The forced wall above is now saved in history — its *local estimate*
  // (≈999,999) would immediately trip the local check on the next turn even
  // though its *real* token count was only ~125k. Clear first so the real
  // overflow demo starts from a clean, small history, same as the proven
  // run_scenarios.py run (3 successful large blocks, then a genuine
  // provider rejection on the 4th).
  await clearContext();
  await scene('Новая чистая сессия для настоящего переполнения — стена символов из прошлого шага не должна путать локальную оценку истории', null, 3000);
  if (await send(FACT, 'C.5 факт (2)') !== 'ok') throw new Error('C.5: ожидался успешный ответ');
  if (await send('Подтверди получение одной короткой фразой.', 'C.6 warmup (2)') !== 'ok') {
    throw new Error('C.6: ожидался успешный ответ');
  }
  await scene('Немного истории — теперь три больших смысловых блока подряд, реальный вход растёт по-настоящему', null, 3000);

  const LOCAL_MSG = 'Запрос превышает известный контекстный лимит модели';
  let overflowHit = false;
  for (let i = 1; i <= 4; i++) {
    const block = generateBlock(900 + i, 140_000);
    const outcome = await send(block, `C padding ${i}`);
    if (outcome === 'ok') {
      const req = await readMetric('metricRequest');
      await scene(`Блок ${i}/4 принят. Вход API этого хода: ${req} — история реально приближается к окну модели`, null, i === 1 ? 4000 : 2000);
    } else {
      const err = await lastErrorText();
      const caption = err.includes(LOCAL_MSG)
        ? `Блок ${i}: локальная оценка истории уже превысила окно — «${err}». Запрос не ушёл в API`
        : `Блок ${i}: DeepSeek отклонил запрос — «${err}». Это настоящий отказ провайдера, не локальная эвристика`;
      await scene(caption, null, 7000);
      overflowHit = true;
      break;
    }
  }
  if (!overflowHit) throw new Error('Ожидался отказ (локальный или провайдера) в пределах 4 больших блоков');

  await scrollPanelTo('usageChart');
  await scene('Итоговая таблица сценария C — реальный вход по сотням тысяч токенов за ход, последний ход отклонён', null, 5000);
  await scrollPanelToTop();

  await clearContext();
  await scene('Очищаем испорченную сессию', null, 2000);
  if (await send('Скажи одно короткое приветствие.', 'recovery') !== 'ok') {
    throw new Error('recovery: агент должен снова отвечать после reset()');
  }
  await scene('Агент снова отвечает как обычно — переполнение одной сессии не сломало приложение', null, 6000);

  await scene('agent.py — бюджет и AgentContextLimitError · token_metrics.py — локальная оценка · providers.py — usage и классификация ошибок', null, 5000);

  recording = false; await cameraPromise; socket.close(); chrome.kill(); server.kill();
  const elapsedSeconds = (Date.now() - captureStartedAt) / 1000;
  const realFps = Math.max(1, index / elapsedSeconds);
  console.log(`Кадров: ${index}, реальное время: ${elapsedSeconds.toFixed(1)}s, framerate для ffmpeg: ${realFps.toFixed(2)}`);
  const result = spawnSync(ffmpegPath, ['-y', '-framerate', realFps.toFixed(2), '-i', path.join(framesDir, 'f%05d.png'), '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '23', output], {stdio: 'inherit'});
  // Chrome may hold its profile dir locked for a moment after kill() on
  // Windows — cleanup is best-effort and must never block the video itself.
  try { rmSync(userDataDir, {recursive: true, force: true}); } catch {}
  if (result.status !== 0) throw new Error('ffmpeg завершился с ошибкой');
  console.log(`Видео: ${output}`);
}

main().catch(error => {
  recording = false;
  try { chrome.kill(); } catch {}
  try { server.kill(); } catch {}
  try { rmSync(userDataDir, {recursive: true, force: true}); } catch {}
  console.error(error.message);
  process.exit(1);
});
