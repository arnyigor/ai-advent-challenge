#!/usr/bin/env node
import {spawn, spawnSync} from 'node:child_process';
import {mkdirSync, rmSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const dayDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(dayDir, '..');
const framesDir = path.resolve(dayDir, 'video-frames');
if (!framesDir.startsWith(dayDir + path.sep)) throw new Error('Некорректная папка кадров');
rmSync(framesDir, {recursive: true, force: true});
mkdirSync(framesDir, {recursive: true});

const pageUrl = process.env.DAY06_WEB_URL;
if (!pageUrl) throw new Error('Задай DAY06_WEB_URL адресом запущенного web_server.py');
const chromePath = process.env.CHROME_PATH || path.join(process.env.ProgramFiles || '', 'Google', 'Chrome', 'Application', 'chrome.exe');
const ffmpegPath = process.env.FFMPEG_PATH || 'ffmpeg';
const cdpPort = Number(process.env.DAY06_CDP_PORT || 0);
if (!Number.isInteger(cdpPort) || cdpPort < 1) throw new Error('Задай DAY06_CDP_PORT свободным локальным портом');
const output = process.argv.includes('--out')
  ? path.resolve(process.argv[process.argv.indexOf('--out') + 1])
  : path.resolve(rootDir, 'ChallengeVideos', 'day06-demo.mp4');
mkdirSync(path.dirname(output), {recursive: true});

const chrome = spawn(chromePath, [
  '--headless=new', `--remote-debugging-port=${cdpPort}`, '--no-sandbox',
  '--disable-gpu', '--window-size=1440,1000', '--hide-scrollbars', 'about:blank'
], {stdio: 'ignore'});
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function waitJson(url, attempts=40) {
  for (let i=0; i<attempts; i++) {
    try { const response = await fetch(url); if (response.ok) return response.json(); } catch {}
    await sleep(250);
  }
  throw new Error(`Не дождался ${url}`);
}

let socket, callId=0;
const pending = new Map();
function cdp(method, params={}) {
  return new Promise((resolve, reject) => {
    const id = ++callId; pending.set(id, {resolve, reject});
    socket.send(JSON.stringify({id, method, params}));
  });
}
const evaluate = expression => cdp('Runtime.evaluate', {expression, returnByValue:true}).then(x => x.result.value);

let recording = true, index = 0, captureStartedAt = 0;
async function camera() {
  captureStartedAt = Date.now();
  while (recording) {
    const {data} = await cdp('Page.captureScreenshot', {format:'png', optimizeForSpeed:true});
    writeFileSync(path.join(framesDir, `f${String(index++).padStart(5,'0')}.png`), Buffer.from(data, 'base64'));
    await sleep(100);
  }
}

const captionScript = caption => `(() => {
  let bar=document.getElementById('videoCaption');
  if(!bar){bar=document.createElement('div');bar.id='videoCaption';bar.style.cssText='position:fixed;left:0;right:0;bottom:0;z-index:9999;background:#02070bea;color:#ffdf70;border-top:1px solid #345;padding:11px;text-align:center;font:700 17px Segoe UI';document.body.appendChild(bar)}
  bar.textContent=${JSON.stringify(caption)};
})()`;

async function scene(caption, action, duration=4000) {
  if (action) await evaluate(action);
  await evaluate(captionScript(caption));
  await sleep(duration);
}

async function waitFor(expression, attempts=140) {
  for (let i=0; i<attempts; i++) {
    if (await evaluate(expression)) return true;
    await sleep(250);
  }
  return false;
}

async function requireAnswer(expectedCount, label) {
  const ok = await waitFor(
    `document.querySelectorAll('.message.assistant:not(.pending):not(.welcome)').length>=${expectedCount}`
  );
  if (!ok) throw new Error(`${label}: ответ не пришёл за отведённое время — запись остановлена, а не подделана`);
  const errorShown = await evaluate("document.querySelector('.message.error')!==null");
  if (errorShown) throw new Error(`${label}: агент вернул ошибку — видно в чате`);
}

async function requireRetryButton(label) {
  const ok = await waitFor("document.querySelector('.message.error .retry-button')!==null");
  if (!ok) throw new Error(`${label}: кнопка «Повторить» не появилась — запись остановлена`);
}

const sendMessageScript = text => `(() => {
  const ta=document.getElementById('prompt');
  ta.value=${JSON.stringify(text)};
  ta.dispatchEvent(new Event('input'));
  document.getElementById('form').requestSubmit();
})()`;

async function main() {
  const targets = await waitJson(`http://127.0.0.1:${cdpPort}/json`);
  socket = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise(resolve => socket.onopen = resolve);
  socket.onmessage = event => { const msg=JSON.parse(event.data); if(msg.id&&pending.has(msg.id)){const p=pending.get(msg.id);pending.delete(msg.id);msg.error?p.reject(new Error(msg.error.message)):p.resolve(msg.result)}};
  await cdp('Page.enable'); await cdp('Runtime.enable');
  await cdp('Page.navigate', {url:pageUrl});
  await waitFor("document.getElementById('configChips')!==null && document.querySelectorAll('#configChips .config-chip').length>0 && !document.querySelector('#configChips .loading')");
  await sleep(600);
  const cameraPromise = camera();

  await scene('Day 06 · Первый агент — ChatAgent инкапсулирует историю, конфиг и вызов LLM API', null, 5000);
  await scene('Agent Box: температура, лимиты, reasoning, policies — заданы внутри агента, не в UI', `window.scrollTo({top:0,behavior:'smooth'})`, 5000);

  await evaluate(sendMessageScript('Объясни коротко, чем агент отличается от одного вызова API'));
  await scene('Интерфейс отправляет только текст. ChatAgent сам собирает сообщение и вызывает провайдера', null, 3000);
  await requireAnswer(1, 'Первый ответ');
  await scene('Ответ отрендерен из markdown: жирный текст, списки и код — не сырые ** и ```, а HTML', null, 9000);

  await evaluate(sendMessageScript('А ты помнишь, о чём я только что спросил?'));
  await scene('Второй вопрос отправлен — проверяем, хранит ли агент контекст сессии', null, 2500);
  await requireAnswer(2, 'Второй ответ');
  await scene('Второй ответ ссылается на первый — агент сам хранит контекст сессии', null, 9000);

  await scene(
    'Вся история диалога видна в чате: оба вопроса и оба ответа с provider/model/токенами',
    `(() => { const chat=document.getElementById('chat'); chat.scrollTo({top:0,behavior:'smooth'}); })()`,
    4000,
  );
  await scene(
    'Прокручиваем вниз — история сохраняется полностью, ничего не обрезается',
    `(() => { const chat=document.getElementById('chat'); chat.scrollTo({top:chat.scrollHeight,behavior:'smooth'}); })()`,
    4000,
  );

  await evaluate(`(() => { providerSelect.value = 'gemini'; thinkingSelect.value = 'high'; })()`);
  await evaluate(sendMessageScript('Подробно объясни разницу между процессом и потоком в ОС'));
  await scene('Отправили тяжёлый запрос на Gemini с high reasoning — сейчас нажмём «Стоп»', null, 2000);
  await evaluate(`document.getElementById('stopButton').click()`);
  await requireRetryButton('Отмена запроса');
  await scene('Запрос отменён — история и токены не изменились, но текст не потерян', null, 3500);
  await scene('У отменённого и у ошибочного ответа одна и та же кнопка «Повторить»', `document.querySelector('.retry-button')?.scrollIntoView({block:'center'})`, 3000);
  await evaluate(`(() => { providerSelect.value = 'deepseek'; thinkingSelect.value = 'minimal'; })()`);
  await evaluate(`document.querySelector('.retry-button').click()`);
  await scene('«Повторить» пересылает тот же текст без повторного ввода — ждём реальный ответ', null, 3000);
  await requireAnswer(3, 'Ответ после повтора');
  await scene('Повтор дошёл до LLM и получил реальный ответ — текст не потерялся при отмене', null, 8000);

  await evaluate(`document.getElementById('resetButton').click()`);
  await sleep(800);
  await scene('Очистка контекста — история и счётчик токенов сбрасываются агентом', null, 4000);

  recording=false; await cameraPromise; socket.close(); chrome.kill();
  const elapsedSeconds = (Date.now() - captureStartedAt) / 1000;
  const realFps = Math.max(1, index / elapsedSeconds);
  console.log(`Кадров: ${index}, реальное время: ${elapsedSeconds.toFixed(1)}s, framerate для ffmpeg: ${realFps.toFixed(2)}`);
  const result = spawnSync(ffmpegPath, ['-y','-framerate',realFps.toFixed(2),'-i',path.join(framesDir,'f%05d.png'),'-vf','scale=trunc(iw/2)*2:trunc(ih/2)*2','-c:v','libx264','-pix_fmt','yuv420p','-crf','23',output], {stdio:'inherit'});
  if(result.status!==0) throw new Error('ffmpeg завершился с ошибкой');
  console.log(`Видео: ${output}`);
}

main().catch(error => {recording=false;try{chrome.kill()}catch{};console.error(error.message);process.exit(1)});
