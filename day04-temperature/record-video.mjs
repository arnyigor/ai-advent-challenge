#!/usr/bin/env node
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
const CDP_PORT = 9226;
const URL = 'http://127.0.0.1:8766/';
const CAPTURE_MS = 15;

const args = process.argv.slice(2);
const flag = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
const outArg = flag('--out') || path.join(ROOT_DIR, 'ChallengeVideos', 'day04-demo.mp4');
mkdirSync(path.dirname(outArg), { recursive: true });

const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${CDP_PORT}`, '--no-sandbox',
  '--disable-gpu', '--window-size=1600,1000', '--force-device-scale-factor=1', '--hide-scrollbars', 'about:blank'
], { stdio: 'ignore' });

async function waitForCDP() {
  for (let i = 0; i < 30; i++) {
    try { const r = await fetch(`http://127.0.0.1:${CDP_PORT}/json`); if (r.ok) return r.json(); } catch {}
    await sleep(500);
  }
  throw new Error('CDP не ответил');
}

let ws, msgId = 0;
const pending = new Map();
function cdp(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++msgId;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error(method + ' timeout')); } }, 45000);
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ev = (expr) => cdp('Runtime.evaluate', { expression: expr, returnByValue: true }).then((r) => r.result.value);

async function waitFor(expr, timeoutMs = 30000, label = '') {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try { const v = await ev(expr); if (v) return v; } catch {}
    await sleep(350);
  }
  throw new Error('Таймаут: ' + (label || expr));
}

let frameIdx = 0, cameraOn = false, captureStartAt = 0, actualFps = 0;

const INJECT_PERSISTENT_JS = `(() => {
  if (window.__captionInstalled) return;
  window.__captionInstalled = true;
  const updater = () => {
    const caption = window.__caption || 'Day 04 — Температура: один промпт, меняется только temperature';
    let bar = document.getElementById('recordCaptionBar');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'recordCaptionBar';
      bar.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:99999;background:rgba(10,14,20,0.94);color:#ffe866;font:600 16px/1.4 sans-serif;padding:10px 20px;text-align:center;border-top:2px solid #2e3846';
      document.body.appendChild(bar);
    }
    bar.textContent = caption;
  };
  setInterval(updater, 250); updater();
})();`;

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
  console.log('✦ [1/8] Запуск Chrome CDP...');
  const targets = await waitForCDP();
  ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (evMsg) => {
    const msg = JSON.parse(evMsg.data);
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id); pending.delete(msg.id);
      msg.error ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result);
    }
  };
  await cdp('Page.enable'); await cdp('Runtime.enable');
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await cdp('Page.navigate', { url: URL });

  console.log('✦ [2/8] Загрузка интерфейса...');
  await waitFor(`document.getElementById('runButton') !== null`, 15000, 'кнопка запуска');

  cameraOn = true; const camPromise = camera();

  console.log('✦ [3/8] Сцена: intro');
  await ev(`window.setScene('intro', 'Один промпт, одна модель. Меняется только temperature')`);
  await sleep(3000);

  console.log('✦ [4/8] Сцена: locked');
  await ev(`window.setScene('locked', 'Зафиксировано всё, кроме одного параметра')`);
  await ev(`document.querySelector('.locked-banner').scrollIntoView({behavior: 'smooth'})`);
  await sleep(4000);

  console.log('✦ [5/8] Сцена: running');
  await ev(`window.setScene('running', '3 температуры × 3 прогона = 9 вызовов')`);
  await ev(`document.getElementById('runButton').click()`);
  // DeepSeek отвечает ~30-60 с на вызов: 9 вызовов / concurrency 3 ≈ 3-5 минут.
// Таймаут закладываем с запасом (480 с), иначе видео оборвётся на [5/8].
await waitFor(`(() => { const s = document.getElementById('statusLabel')?.textContent || ''; return s === 'DONE' || s === 'FAILED' || s === 'STOPPED'; })()`, 480000, 'завершение');
  await sleep(2000);

  console.log('✦ [6/8] Сцена: diversity');
  await ev(`window.setScene('diversity', '0.0 — ответы почти совпадают. 1.2 — расходятся')`);
  await ev(`document.querySelector('.metric-box').scrollIntoView({behavior: 'smooth'})`);
  await sleep(5000);

  console.log('✦ [7/8] Сцена: analogies');
  await ev(`window.setScene('analogies', 'Девять аналогий: креативность видно без баллов')`);
  await ev(`document.querySelector('.tab[data-tab="analogies"]').click()`);
  await sleep(7000);

  console.log('✦ [8/8] Сцена: metrics & verdict');
  await ev(`window.setScene('metrics', 'Цена высокой температуры: обрывы и неточности')`);
  await ev(`document.querySelector('.tab[data-tab="metrics"]').click()`);
  await sleep(6000);
  await ev(`window.setScene('verdict', '0.0 факты · 0.7 объяснения · 1.2 брейншторм')`);
  await sleep(5000);

  cameraOn = false; await camPromise;
  console.log(`✦ Снято кадров: ${frameIdx} (fps: ${actualFps.toFixed(2)})`);
  ws.close(); chrome.kill();

  console.log('✦ Сборка MP4...');
  execSync(`"${FFMPEG}" -y -framerate ${actualFps.toFixed(3)} -i "${path.join(VIDEO_DIR, 'f%04d.png')}" -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" -c:v libx264 -pix_fmt yuv420p -crf 23 "${outArg}"`, { stdio: 'pipe' });
  console.log(`\n✓ Видео: ${outArg}\n`);
}

main().catch((e) => { console.error('Ошибка:', e.message); try { chrome.kill(); } catch {} process.exit(1); });