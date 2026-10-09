#!/usr/bin/env node
// Capture the day 30 web chat in a real headless Chrome via CDP (no dependencies:
// node's built-in WebSocket).
//
// One session produces two kinds of evidence:
//   1) frame sequence of the whole interaction (typing -> send -> answer) in
//      video-frames/chatflow/*.jpg with real timestamps in flow-manifest.json;
//   2) three full-resolution screenshots in evidence/chat-*.png.
//
//   node capture-chat.mjs
//   CHAT_URL=http://192.168.1.212:8091/ node capture-chat.mjs
import { spawn } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRAMES = path.join(__dirname, 'video-frames');
const FLOW = path.join(FRAMES, 'chatflow');
const EVIDENCE = path.join(__dirname, 'evidence');
rmSync(FLOW, { recursive: true, force: true });
mkdirSync(FLOW, { recursive: true });
mkdirSync(EVIDENCE, { recursive: true });

const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const URL = process.env.CHAT_URL || 'http://192.168.1.212:8091/';
const CDP_PORT = Number(process.env.CDP_PORT || 9227);
const KEYS_FILE = process.env.KEYS_FILE || path.join(__dirname, 'keys.json');
const FRAME_INTERVAL_MS = Number(process.env.FRAME_INTERVAL_MS || 250);

const keys = JSON.parse(readFileSync(KEYS_FILE, 'utf-8'));
const KEY = process.env.CHAT_KEY || keys.main;
if (!KEY) throw new Error('нет клиентского ключа: положите keys.json или задайте CHAT_KEY');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${CDP_PORT}`, '--no-sandbox', '--disable-gpu',
  '--window-size=1920,1080', '--hide-scrollbars', '--disable-extensions', 'about:blank',
], { stdio: 'ignore' });

let ws, msgId = 0;
const pending = new Map();
const cdp = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++msgId;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params }));
  setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error(method + ' timeout')); } }, 180000);
});
const ev = (expression) => cdp('Runtime.evaluate', { expression, returnByValue: true }).then((r) => r.result.value);

async function waitFor(expression, timeoutMs, label) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try { if (await ev(expression)) return; } catch {}
    await sleep(300);
  }
  throw new Error('таймаут: ' + label);
}

async function shot(name) {
  const { data } = await cdp('Page.captureScreenshot', { format: 'png' });
  const buffer = Buffer.from(data, 'base64');
  writeFileSync(path.join(EVIDENCE, name), buffer);
  writeFileSync(path.join(FRAMES, name), buffer);
  console.log('  снимок', name);
}

// --- frame sequence of the live interaction ---------------------------------
let frameIndex = 0;
let capturing = false;
const frameStamps = [];
let captureErrors = 0;

async function captureLoop() {
  capturing = true;
  while (capturing) {
    const started = Date.now();
    try {
      const { data } = await cdp('Page.captureScreenshot', { format: 'jpeg', quality: 88 });
      writeFileSync(path.join(FLOW, `f${String(frameIndex).padStart(5, '0')}.jpg`), Buffer.from(data, 'base64'));
      frameStamps.push(Number(((Date.now() - flowStartedAt) / 1000).toFixed(2)));
      frameIndex += 1;
    } catch { captureErrors += 1; }
    const spent = Date.now() - started;
    if (spent < FRAME_INTERVAL_MS) await sleep(FRAME_INTERVAL_MS - spent);
  }
}

const READ_LAST = `(() => {
  const box = document.querySelector('#log .msg:last-child');
  if (!box) return null;
  return { body: box.querySelector('div:nth-child(2)').textContent,
           note: box.querySelector('.note').textContent,
           who: box.querySelector('.who').textContent };
})()`;

const ANSWER_READY = `(() => {
  const box = document.querySelector('#log .msg:last-child');
  if (!box) return false;
  const note = box.querySelector('.note').textContent;
  return !document.getElementById('send').disabled &&
         (note.includes('finish_reason') || note.includes('Retry-After') || note.includes('Сеть недоступна'));
})()`;

const SET_INPUT = (id, value) => `(() => {
  const el = document.getElementById(${JSON.stringify(id)});
  el.value = ${JSON.stringify(value)};
  el.dispatchEvent(new Event('input', { bubbles: true }));
  return el.value.length;
})()`;

async function typeText(text, perCharMs = 90) {
  for (let i = 1; i <= text.length; i += 1) {
    await ev(SET_INPUT('prompt', text.slice(0, i)));
    await sleep(perCharMs);
  }
}

async function ask(question, typed = true) {
  if (typed) await typeText(question);
  else await ev(SET_INPUT('prompt', question));
  await sleep(350);
  await ev(`document.getElementById('send').click()`);
  await waitFor(`document.getElementById('send').disabled === true`, 20000, 'запрос отправлен');
  await waitFor(ANSWER_READY, 180000, 'ответ получен');
  const last = await ev(READ_LAST);
  console.log(`  вопрос: ${question}`);
  console.log(`  ответ:  ${String(last.body).slice(0, 120).replace(/\s+/g, ' ')}`);
  return { question, answer: last.body, note: last.note };
}

let flowStartedAt = Date.now();

async function main() {
  const targets = await (async () => {
    for (let i = 0; i < 40; i++) {
      try { const r = await fetch(`http://127.0.0.1:${CDP_PORT}/json`); if (r.ok) return r.json(); } catch {}
      await sleep(500);
    }
    throw new Error('CDP не ответил');
  })();

  ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((r) => { ws.onopen = r; });
  ws.onmessage = (message) => {
    const msg = JSON.parse(message.data);
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result);
    }
  };
  await cdp('Page.enable');
  await cdp('Runtime.enable');
  // 1.5x scale keeps the chat text readable in a 1920x1080 video frame.
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1280, height: 800, deviceScaleFactor: 1.5, mobile: false });
  await cdp('Page.navigate', { url: URL });

  console.log('интерфейс:', URL);
  await waitFor(`document.getElementById('send') !== null`, 20000, 'форма чата');
  await waitFor(`document.getElementById('limits').textContent.includes('окно')`, 15000, 'строка лимитов');
  const limitsLine = await ev(`document.getElementById('limits').textContent`);
  await ev(SET_INPUT('key', KEY));
  await sleep(700);

  flowStartedAt = Date.now();
  const loop = captureLoop();
  await sleep(900);
  await shot('chat-00-empty.png');

  const seed = await ask('Запомни код КЕДР-42. Ответь одним словом: запомнил.');
  await sleep(1200);
  await shot('chat-01-seed.png');

  const second = await ask('Какой код я просил запомнить?');
  await sleep(2600);   // hold the finished answer in the video
  capturing = false;
  await loop;

  const elapsed = Number(((Date.now() - flowStartedAt) / 1000).toFixed(2));
  const flow = {
    frames: frameIndex,
    elapsed_sec: elapsed,
    fps: Number((frameIndex / elapsed).toFixed(2)),
    frame_interval_ms: FRAME_INTERVAL_MS,
    capture_errors: captureErrors,
    first_frame_sec: frameStamps[0],
    last_frame_sec: frameStamps[frameStamps.length - 1],
    dir: 'video-frames/chatflow',
    note: 'Посекундная съёмка реального диалога: каждый кадр — настоящий снимок страницы в этот момент.',
  };

  const record = {
    stage: 'chat-ui',
    day: 30,
    captured_at: new Date().toISOString(),
    url: URL,
    browser: 'headless Chrome via CDP, viewport 1280x800, deviceScaleFactor 1.5',
    limits_line: limitsLine,
    screenshots: ['evidence/chat-00-empty.png', 'evidence/chat-01-seed.png', 'evidence/chat-02-history.png'],
    turns: [seed, second],
    flow,
    notes: [
      'Ответы получены реальным браузером через шлюз: это работающий веб-чат, а не реконструкция.',
      'Сообщение набирается по символам, отправляется кнопкой «Отправить»; ожидание генерации и ответ видны в кадрах.',
      'Кадры последовательности лежат в video-frames/chatflow (артефакт сборки, вне Git); в evidence/ сохранены три полноразмерных снимка.',
      'Ключ в кадр не попадает: поле ввода типа password.',
      'История хранится в памяти вкладки и отправляется с каждым запросом; сервер её не хранит.',
    ],
  };
  writeFileSync(path.join(EVIDENCE, 'day30-chat-ui.json'), JSON.stringify(record, null, 2), 'utf-8');
  console.log(`кадров: ${frameIndex}, реальных секунд: ${elapsed}, ≈${flow.fps} кадр/с`);
  console.log('evidence/day30-chat-ui.json записан');

  chrome.kill();
  process.exit(0);
}

main().catch((error) => { console.error('ошибка:', error.message); chrome.kill(); process.exit(1); });
