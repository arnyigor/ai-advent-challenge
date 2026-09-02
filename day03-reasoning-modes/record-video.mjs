#!/usr/bin/env node
// record-video.mjs — Автоматическая запись демо-видео Day 03 (Reasoning Lab · DeepSeek)
// Стек: Node.js 22+ (встроенный WebSocket), Headless Chrome (CDP), FFmpeg.
// Ноль npm-зависимостей.
//
// Запуск:
//   node record-video.mjs
//   node record-video.mjs --out ../ChallengeVideos/day03-demo.mp4

import { spawn, execSync } from 'node:child_process';
import { writeFileSync, mkdirSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, '..');
const VIDEO_DIR = path.join(__dirname, 'video-frames');
rmSync(VIDEO_DIR, { recursive: true, force: true });
mkdirSync(VIDEO_DIR, { recursive: true });

const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const FFMPEG = process.env.FFMPEG_PATH || 'ffmpeg';
const CDP_PORT = 9225; // отдельный порт, чтобы не конфликтовать с Day 1
const URL = 'http://127.0.0.1:8765/';
// Реальный fps захвата ограничен латентностью CDP-скриншота (~7-10 fps).
// Собираем кадры максимально быстро, а в FFmpeg кодируем с ИЗМЕРЕННЫМ fps,
// чтобы видео шло в реальном времени, а не «ускоренным».
const CAPTURE_MS = 15; // минимальная пауза между кадрами

const args = process.argv.slice(2);
const flag = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
const outArg = flag('--out') || path.join(ROOT_DIR, 'ChallengeVideos', 'day03-demo.mp4');
mkdirSync(path.dirname(outArg), { recursive: true });

// Тело скрипта динамической плашки субтитров внизу экрана
const CAPTION_BODY = `
  let bar = document.getElementById('recordCaptionBar');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'recordCaptionBar';
    bar.style.cssText = [
      'position:fixed', 'left:0', 'right:0', 'bottom:0', 'z-index:99999',
      'background:rgba(10, 14, 20, 0.94)', 'color:#ffe866',
      'font:600 16px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif',
      'padding:10px 20px', 'text-align:center', 'letter-spacing:0.02em',
      'border-top:2px solid #2e3846', 'box-shadow:0 -4px 16px rgba(0,0,0,0.5)'
    ].join(';');
    document.body.appendChild(bar);
  }

  const $ = (sel) => document.querySelector(sel);
  const status = ($('#statusLabel')?.textContent || '').trim();
  const task = $('#taskInput')?.value || '';
  const model = $('#modelInput')?.value || '';
  const activeCard = document.querySelector('.method-card.active');
  const activeMethod = activeCard?.querySelector('[data-live-label]')?.dataset.liveLabel || '';
  const liveLabel = (activeCard?.querySelector('.live-label')?.textContent || '').trim();
  const isResultsTab = document.querySelector('.tab[data-tab="results"]')?.classList.contains('active');
  const isRawTab = document.querySelector('.tab[data-tab="raw"]')?.classList.contains('active');

  const scorePanel = document.querySelector('.score-panel');
  let scoreVisible = false;
  if (scorePanel) {
    const rect = scorePanel.getBoundingClientRect();
    scoreVisible = rect.top < window.innerHeight && rect.bottom > 100;
  }

  let text = "Day 03 — Сравнение 4 стратегий рассуждения LLM (DeepSeek)";

  if (isRawTab) {
    text = "Raw Data: детерминированный JSON-документ со всеми стадиями сохранен";
  } else if (isResultsTab) {
    text = "Results: итоговая точность, токены, время и Парето-вердикт";
  } else if (status === 'STOPPED') {
    text = "Кнопка STOP: мгновенный разрыв стрима и отмена сессии на бэкенде";
  } else if (scoreVisible && (status === 'RESULTS' || status === 'DONE')) {
    text = "Итог: нормализация ответов, проверка эталона, подсчет токенов и latency";
  } else if (activeMethod === 'self_prompt' && /LEAK|CALL|1\\/2|2\\/2/i.test(liveLabel)) {
    text = "Self-Prompt: CALL 1/2 → проверка утечки (leak_check) → CALL 2/2";
  } else if (activeMethod === 'self_prompt') {
    text = "Self-Prompt: 2 вызова + автоматическая детекция утечки эталона";
  } else if (activeMethod === 'panel') {
    text = "Expert Panel: 3 роли (аналитик, инженер, критик) в 1 промпте за 1 вызов";
  } else if (activeMethod === 'cot') {
    text = "Chain-of-Thought (CoT): пошаговое рассуждение со стримингом токенов";
  } else if (activeMethod === 'direct') {
    text = "Direct: прямой ответ модели без дополнительных инструкций (RPM=0)";
  } else if (task === 'counting-01') {
    text = "Реактивный UI: мгновенная смена задачи counting-01 и выбор DeepSeek";
  }

  bar.textContent = text;
`;

const chrome = spawn(CHROME, [
  '--headless=new',
  `--remote-debugging-port=${CDP_PORT}`,
  '--no-sandbox',
  '--disable-gpu',
  '--window-size=1440,900',
  '--force-device-scale-factor=1',
  '--hide-scrollbars',
  'about:blank'
], { stdio: 'ignore' });

async function waitForCDP() {
  for (let i = 0; i < 30; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${CDP_PORT}/json`);
      if (r.ok) return r.json();
    } catch {}
    await sleep(500);
  }
  throw new Error('CDP не ответил на порту ' + CDP_PORT);
}

let ws, msgId = 0;
const pending = new Map();
function cdp(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++msgId;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id);
        reject(new Error(method + ' timeout'));
      }
    }, 45000);
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ev = (expr) => cdp('Runtime.evaluate', { expression: expr, returnByValue: true }).then((r) => r.result.value);

async function waitFor(expr, timeoutMs = 30000, label = '') {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const v = await ev(expr);
      if (v) return v;
    } catch {}
    await sleep(350);
  }
  throw new Error('Таймаут ожидания: ' + (label || expr));
}

let frameIdx = 0;
let cameraOn = false;
let captureStartAt = 0;
let actualFps = 0;

// Плашка субтитров + автоскролл живут САМИ в странице (setInterval),
// поэтому кадре-цикл не делает лишних CDP-вызовов и снимает быстрее.
const INJECT_PERSISTENT_JS = `(() => {
  if (window.__captionInstalled) return;
  window.__captionInstalled = true;
  window.__stickBottom = false;
  const updater = () => { ${CAPTION_BODY}
    if (window.__stickBottom && window.scrollY < document.body.scrollHeight - window.innerHeight - 5) {
      window.scrollTo(0, document.body.scrollHeight);
    }
  };
  setInterval(updater, 250);
  updater();
})()`;

async function camera() {
  try { await ev(INJECT_PERSISTENT_JS); } catch {}
  captureStartAt = Date.now();
  while (cameraOn) {
    try {
      const t0 = Date.now();
      const { data } = await cdp('Page.captureScreenshot', { format: 'png', optimizeForSpeed: true });
      writeFileSync(path.join(VIDEO_DIR, `f${String(frameIdx++).padStart(4, '0')}.png`), Buffer.from(data, 'base64'));
      const elapsed = Date.now() - t0;
      if (elapsed < CAPTURE_MS) await sleep(CAPTURE_MS - elapsed);
    } catch {}
  }
  actualFps = frameIdx / Math.max(1, (Date.now() - captureStartAt) / 1000);
}

async function main() {
  console.log('✦ [1/6] Запуск Chrome CDP...');
  const targets = await waitForCDP();
  ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (evMsg) => {
    const msg = JSON.parse(evMsg.data);
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result);
    }
  };

  await cdp('Page.enable');
  await cdp('Runtime.enable');
  // Фиксируем вьюпорт 1440x1080 (иначе headless отнимает ~150px от --window-size)
  await cdp('Emulation.setDeviceMetricsOverride', {
    width: 1440, height: 1080, deviceScaleFactor: 1, mobile: false,
  });
  await cdp('Page.navigate', { url: URL });

  console.log('✦ [2/6] Загрузка веб-интерфейса Day 3...');
  await waitFor(`document.querySelectorAll('#taskInput option').length > 0`, 15000, 'список задач');
  await waitFor(`document.querySelectorAll('#modelInput option').length > 0`, 15000, 'список моделей');

  cameraOn = true;
  const camPromise = camera();

  // Начальный экран (2 сек)
  await sleep(2000);

  // Переключение задачи на counting-01 и выбор DeepSeek
  console.log('✦ [3/6] Выбор задачи counting-01 и модели DeepSeek...');
  await ev(`(() => {
    const selTask = document.getElementById('taskInput');
    selTask.value = 'counting-01';
    selTask.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await sleep(1200);

  await ev(`(() => {
    const selModel = document.getElementById('modelInput');
    const opt = [...selModel.options].find(o => o.value.includes('deepseek'));
    if (opt) {
      selModel.value = opt.value;
      selModel.dispatchEvent(new Event('change', { bubbles: true }));
    }
  })()`);
  await sleep(1500);

  // Запуск основного прогона (4 метода)
  console.log('✦ [4/6] Запуск эксперимента (4 метода рассуждений)...');
  await ev(`window.scrollTo({ top: 0, behavior: 'auto' })`);
  await ev(`document.getElementById('runButton').click()`);

  // Ждем старта и скроллим в самый низ: видны карточки и панель сравнения
  await waitFor(
    `(() => (document.getElementById('statusLabel')?.textContent || '').includes('RUNNING'))()`,
    10000,
    'старт прогона'
  );
  await sleep(400);
  await ev(`window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })`);
  await ev(`window.__stickBottom = true`); // карточки растут при стриминге — держим низ в кадре
  await sleep(800);

  // Ждем завершения всех 4 методов
  await waitFor(
    `(() => {
      const status = document.getElementById('statusLabel')?.textContent || '';
      const runBtn = document.getElementById('runButton');
      return status.includes('RESULTS') || (runBtn && !runBtn.disabled && status.includes('DONE'));
    })()`,
    120000,
    'завершение прогона 4 методов'
  );
  console.log('✦ Прогон завершён успешно!');
  await sleep(2500);

  // Показываем таблицу сравнения (Run 1)
  console.log('✦ Показ таблицы результатов...');
  await ev(`window.__stickBottom = true`);
  await sleep(3000);

  // Переключение на вкладки Results и Raw Data ПОЛНОГО прогона
  console.log('✦ [5/6] Демонстрация вкладок Results и Raw Data...');
  await ev(`window.__stickBottom = false`);
  await ev(`window.scrollTo({ top: 0, behavior: 'smooth' })`);
  await sleep(800);

  await ev(`document.querySelector('.tab[data-tab="results"]')?.click()`);
  await sleep(3000);

  await ev(`document.querySelector('.tab[data-tab="raw"]')?.click()`);
  await sleep(3000);

  // Возврат на вкладку Live и демонстрация кнопки STOP (Run 2)
  console.log('✦ [6/6] Демонстрация кнопки STOP на вкладке Live...');
  await ev(`document.querySelector('.tab[data-tab="live"]')?.click()`);
  await sleep(1000);

  await ev(`document.getElementById('runButton').click()`);
  await waitFor(
    `(() => {
      const status = document.getElementById('statusLabel')?.textContent || '';
      const active = document.querySelector('.method-card.active');
      return status.includes('RUNNING') && active !== null;
    })()`,
    15000,
    'старт повторного запуска для STOP'
  );
  await sleep(1800); // даем начаться стримингу

  console.log('✦ Клик "Остановить"...');
  await ev(`document.getElementById('stopButton').click()`);
  await waitFor(
    `(() => (document.getElementById('statusLabel')?.textContent || '').includes('STOPPED'))()`,
    10000,
    'остановка прогона'
  );
  await sleep(3000);

  cameraOn = false;
  await camPromise;
  console.log(`✦ Снято кадров: ${frameIdx} (реальный fps захвата: ${actualFps.toFixed(2)})`);

  ws.close();
  chrome.kill();

  // Сборка финального MP4 через FFmpeg
  console.log('✦ Сборка MP4 через FFmpeg...');
  execSync(
    `"${FFMPEG}" -y -framerate ${actualFps.toFixed(3)} -i "${path.join(VIDEO_DIR, 'f%04d.png')}" ` +
    `-vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" -c:v libx264 -pix_fmt yuv420p -crf 23 "${outArg}"`,
    { stdio: 'pipe' }
  );

  console.log(`\n============================================================`);
  console.log(`✓ Видео успешно записано: ${outArg}`);
  console.log(`============================================================\n`);
}

main().catch((e) => {
  console.error('Ошибка записи видео:', e.message);
  try { chrome.kill(); } catch {}
  process.exit(1);
});