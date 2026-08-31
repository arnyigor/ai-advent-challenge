// record-video.mjs — записывает видео-демо LLM-интерфейса
//
// Как это работает:
//   1. Запускает headless Chrome с CDP (remote debugging port)
//   2. Открывает http://localhost:3000, ждёт детекта бэкендов
//   3. «Камера» снимает скриншоты страницы каждые 125мс (8 fps) через CDP
//   4. Сценарий: для каждого бэкенда — клик по чипу → печатает запрос
//      посимвольно → отправляет → ждёт завершения стриминга ответа
//   5. ffmpeg собирает кадры в mp4 (H.264)
//
// Запуск:
//   node record-video.mjs                                # все доступные бэкенды
//   node record-video.mjs --backends llama.cpp,deepseek  # выборочные
//   node record-video.mjs --out video/my-demo.mp4        # свой путь
//
// Требования: сервер запущен (run.bat), Chrome и ffmpeg доступны.
// Пути можно переопределить переменными окружения CHROME_PATH и FFMPEG_PATH.
// Ноль npm-зависимостей (встроенный WebSocket в Node 22+).

import { spawn, execSync } from 'node:child_process';
import { writeFileSync, mkdirSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const VIDEO_DIR = path.join(__dirname, 'video');
const FRAMES_DIR = path.join(VIDEO_DIR, 'frames');
rmSync(FRAMES_DIR, { recursive: true, force: true });
mkdirSync(FRAMES_DIR, { recursive: true });

// Chrome: переопределить через CHROME_PATH (иначе стандартный путь установки Windows)
const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
// ffmpeg: лучше всего — в PATH; свой путь задать через FFMPEG_PATH
const FFMPEG = process.env.FFMPEG_PATH || 'ffmpeg';
const PORT = 9224;
const URL = 'http://localhost:3000';
const FPS = 8;
const CAPTURE_MS = 125; // 8 fps

// --- аргументы ---
const args = process.argv.slice(2);
const flag = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
const backendsArg = flag('--backends');
const outArg = flag('--out') || path.join(VIDEO_DIR, 'llm-demo.mp4');

// сценарий по бэкендам: label в UI → промпт для записи
const SCENARIO = {
  'llama.cpp': { label: 'llama.cpp', prompt: 'Напиши 2 строчки стиха о коде и отладке' },
  'ollama':    { label: 'Ollama',    prompt: 'Скажи одно слово: приветствие' },
  'deepseek':  { label: 'DeepSeek',  prompt: 'Одно предложение: что такое LLM?' },
  'openai':    { label: 'OpenAI',    prompt: 'Одно предложение: что такое API?' },
  'gemini':    { label: 'Gemini',    prompt: 'Скажи 3 слова про космос' },
  'mock':      { label: 'Mock',      prompt: 'тест' },
};

const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--no-sandbox',
  '--disable-gpu', '--window-size=1280,800', '--hide-scrollbars', 'about:blank'
], { stdio: 'ignore' });

async function waitForCDP() {
  for (let i = 0; i < 30; i++) {
    try { const r = await fetch(`http://127.0.0.1:${PORT}/json`); if (r.ok) return r.json(); } catch {}
    await sleep(500);
  }
  throw new Error('CDP не ответил');
}

let ws, id = 0;
const pending = new Map();
function cdp(method, params = {}) {
  return new Promise((resolve, reject) => {
    const msgId = ++id;
    pending.set(msgId, { resolve, reject });
    ws.send(JSON.stringify({ id: msgId, method, params }));
    setTimeout(() => { if (pending.has(msgId)) { pending.delete(msgId); reject(new Error(method + ' timeout')); } }, 20000);
  });
}
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const ev = (expr) => cdp('Runtime.evaluate', { expression: expr, returnByValue: true }).then(r => r.result.value);

let frameIdx = 0;
async function capture() {
  const { data } = await cdp('Page.captureScreenshot', { format: 'png' });
  writeFileSync(path.join(FRAMES_DIR, `f${String(frameIdx++).padStart(4, '0')}.png`), Buffer.from(data, 'base64'));
}

// фоновая камера
let cameraOn = false;
async function camera() { while (cameraOn) { await capture(); await sleep(CAPTURE_MS); } }

// фоновый скроллер: UI скроллит чат только при создании сообщения,
// а длинный стриминг уходит за низ вьюпорта — держим чат прижатым к низу
let scrollerOn = false;
async function scroller() {
  while (scrollerOn) {
    await ev(`(() => { const c = document.getElementById('chat'); c.scrollTop = c.scrollHeight; })()`);
    await sleep(300);
  }
}

async function main() {
  console.log('✦ Chrome...');
  const targets = await waitForCDP();
  ws = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  ws.onmessage = (evMsg) => {
    const msg = JSON.parse(evMsg.data);
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id); pending.delete(msg.id);
      msg.error ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result);
    }
  };

  await cdp('Page.enable');
  await cdp('Runtime.enable');
  await cdp('Page.navigate', { url: URL });

  // ждём детект бэкендов (Gemini может занять до 15 с)
  // доступные чипы = .chip без класса .disabled
  console.log('✦ Ждём детект бэкендов...');
  let chips = 0;
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    chips = await ev(`document.querySelectorAll('.chip:not(.disabled)').length`);
    if (chips) break;
  }
  if (!chips) throw new Error('Бэкенды не загрузились');
  const available = await ev(`[...document.querySelectorAll('.chip:not(.disabled)')].map(c=>c.textContent.trim())`);
  console.log('✦ Доступно:', available.join(', '));

  // какие бэкенды снимать
  let plan = backendsArg ? backendsArg.split(',') : Object.keys(SCENARIO);
  plan = plan.filter((b) => SCENARIO[b] && available.some((a) => a.startsWith(SCENARIO[b].label)));
  if (!plan.length) throw new Error('Нет доступных бэкендов для записи');
  console.log('✦ План записи:', plan.join(', '));

  cameraOn = true;
  scrollerOn = true;
  const cam = camera();
  const scr = scroller();

  // стартовое состояние
  console.log('✦ [0] Стартовое состояние (3 c)');
  await sleep(3000);

  for (const b of plan) {
    const { label, prompt } = SCENARIO[b];
    console.log(`✦ [${b}] выбираю чип...`);
    await ev(`[...document.querySelectorAll('.chip')].find(c=>c.textContent.trim().startsWith('${label}'))?.click()`);
    await sleep(800);

    console.log(`✦ [${b}] печатаю: «${prompt}»`);
    for (const ch of prompt) {
      await ev(`document.getElementById('prompt').value += ${JSON.stringify(ch)}`);
      await sleep(55);
    }
    await sleep(600);

    console.log(`✦ [${b}] отправляю, жду стриминг...`);
    const before = await ev(`document.querySelectorAll('#chat .msg').length`);
    await ev(`document.getElementById('form').dispatchEvent(new Event('submit', {cancelable:true}))`);

    // ждём НОВОЕ сообщение (после отправки) с .meta (done) или с ошибкой
    let done = false;
    for (let i = 0; i < 120; i++) {
      await sleep(500);
      done = await ev(`(() => {
        const msgs = document.querySelectorAll('#chat .msg');
        if (msgs.length <= ${before}) return false;
        const last = msgs[msgs.length - 1];
        return !!last.querySelector('.meta') || last.classList.contains('error');
      })()`);
      if (done) break;
    }
    console.log(`✦ [${b}] ответ готов${done ? '' : ' (таймаут)'} — держу 2.5 c`);
    await sleep(2500);
  }

  cameraOn = false;
  scrollerOn = false;
  await cam;
  await scr;
  console.log(`✦ Кадров: ${frameIdx}`);
  ws.close();
  chrome.kill();

  // сборка видео (scale — высота должна быть чётной для yuv420p)
  console.log('✦ Собираю mp4...');
  execSync(
    `${FFMPEG} -y -framerate ${FPS} -i "${path.join(FRAMES_DIR, 'f%04d.png')}" ` +
    `-vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" -c:v libx264 -pix_fmt yuv420p -crf 23 "${outArg}"`,
    { stdio: 'pipe' }
  );
  console.log(`✓ Видео: ${outArg}`);
}

main().catch(e => { console.error('Ошибка:', e.message); try { chrome.kill(); } catch {} process.exit(1); });
