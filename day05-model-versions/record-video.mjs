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

const pageUrl = process.env.DAY05_WEB_URL;
if (!pageUrl) throw new Error('Задай DAY05_WEB_URL адресом запущенного dashboard');
const chromePath = process.env.CHROME_PATH || path.join(process.env.ProgramFiles || '', 'Google', 'Chrome', 'Application', 'chrome.exe');
const ffmpegPath = process.env.FFMPEG_PATH || 'ffmpeg';
const cdpPort = Number(process.env.DAY05_CDP_PORT || 0);
if (!Number.isInteger(cdpPort) || cdpPort < 1) throw new Error('Задай DAY05_CDP_PORT свободным локальным портом');
const output = process.argv.includes('--out')
  ? path.resolve(process.argv[process.argv.indexOf('--out') + 1])
  : path.resolve(rootDir, 'ChallengeVideos', 'day05-demo.mp4');
mkdirSync(path.dirname(output), {recursive: true});

const chrome = spawn(chromePath, [
  '--headless=new', `--remote-debugging-port=${cdpPort}`, '--no-sandbox',
  '--disable-gpu', '--window-size=1600,1000', '--hide-scrollbars', 'about:blank'
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

let recording = true, index = 0;
async function camera() {
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

async function main() {
  const targets = await waitJson(`http://127.0.0.1:${cdpPort}/json`);
  socket = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise(resolve => socket.onopen = resolve);
  socket.onmessage = event => { const msg=JSON.parse(event.data); if(msg.id&&pending.has(msg.id)){const p=pending.get(msg.id);pending.delete(msg.id);msg.error?p.reject(new Error(msg.error.message)):p.resolve(msg.result)}};
  await cdp('Page.enable'); await cdp('Runtime.enable');
  await cdp('Page.navigate', {url:pageUrl});
  for(let i=0;i<40;i++){if(await evaluate("document.getElementById('replaySelect')!==null"))break;await sleep(250)}
  await sleep(1200);
  const cameraPromise = camera();

  await scene('Day 05 · один запрос на девяти моделях: HF, API и local', null, 3500);
  await evaluate(`(() => { const s=document.getElementById('replaySelect'); if(s.options.length>1){s.value=s.options[1].value;s.dispatchEvent(new Event('change'))} })()`);
  for(let i=0;i<60;i++){if(await evaluate("document.getElementById('statusLabel').textContent==='DONE'"))break;await sleep(250)}
  await scene('Одинаковые prompt, temperature и лимит. HF-модели работают у одного провайдера.', null, 4500);
  await scene('Качество видно объективно: сгенерированный код проходит 10 тестов.', `document.querySelector('.tab[data-tab="score"]').click()`, 7000);
  await scene('Сравниваем latency, TTFT, tokens/s, токены и фактическую стоимость.', null, 6000);
  await scene('Для local измерены VRAM или CPU/RAM; API-стоимость локальных равна нулю.', `window.scrollTo({top:document.documentElement.scrollHeight,behavior:'smooth'})`, 6000);
  await scene('Финал: сильнее не всегда значит выгоднее — важен баланс качества, скорости и цены.', null, 5000);

  recording=false; await cameraPromise; socket.close(); chrome.kill();
  const result = spawnSync(ffmpegPath, ['-y','-framerate','10','-i',path.join(framesDir,'f%05d.png'),'-vf','scale=trunc(iw/2)*2:trunc(ih/2)*2','-c:v','libx264','-pix_fmt','yuv420p','-crf','23',output], {stdio:'inherit'});
  if(result.status!==0) throw new Error('ffmpeg завершился с ошибкой');
  console.log(`Видео: ${output}`);
}

main().catch(error => {recording=false;try{chrome.kill()}catch{};console.error(error.message);process.exit(1)});
