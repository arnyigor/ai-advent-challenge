// День 34: реальный браузерный прогон через CDP. Без подставных ответов модели.
// Адаптация capture-demo.mjs дня 31 под UI файлового ассистента.
import {spawn} from 'node:child_process';
import {existsSync, mkdirSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const DAY = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(DAY, 'evidence');
const FRAMES = path.join(DAY, 'video-frames');
mkdirSync(OUT, {recursive: true});
mkdirSync(FRAMES, {recursive: true});
const chromePath = process.env.CHROME_PATH || [process.env.PROGRAMFILES, process.env['PROGRAMFILES(X86)'], process.env.LOCALAPPDATA]
  .filter(Boolean).map((p) => path.join(p, 'Google', 'Chrome', 'Application', 'chrome.exe')).find(existsSync);
if (!chromePath) throw new Error('Set CHROME_PATH');
const port = Number(process.env.DAY34_CDP_PORT || 9234);
const serverPort = process.env.DAY34_WEB_PORT || 8834;
const url = process.env.DAY34_DEMO_URL || `http://127.0.0.1:${serverPort}/`;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const chrome = spawn(chromePath, ['--headless=new', `--remote-debugging-port=${port}`,
  `--user-data-dir=${path.join(FRAMES, `browser-${Date.now()}`)}`, '--disable-gpu', '--hide-scrollbars',
  '--disable-extensions', '--no-first-run', '--no-default-browser-check', '--window-size=1600,900', 'about:blank'], {stdio:'ignore'});
let socket;
let nextId = 0;
const pending = new Map();
const cdp = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++nextId;
  const timer = setTimeout(() => { pending.delete(id); reject(new Error(`${method} timeout`)); }, 20000);
  pending.set(id, {resolve, reject, timer});
  socket.send(JSON.stringify({id, method, params}));
});
const evaluate = async (expression) => (await cdp('Runtime.evaluate', {expression, returnByValue: true})).result.value;
async function waitFor(expression, timeout=300000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (await evaluate(expression)) return;
    await sleep(400);
  }
  throw new Error(`Browser timeout: ${expression}`);
}
async function shot(name) {
  await sleep(300);
  const {data} = await cdp('Page.captureScreenshot', {format:'png'});
  writeFileSync(path.join(OUT, name), Buffer.from(data, 'base64'));
  console.log(name);
}
async function focusShot(name, selector) {
  const clip = await evaluate(`(() => {const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height,scale:1};})()`);
  const {data}=await cdp('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip});
  writeFileSync(path.join(OUT,name),Buffer.from(data,'base64'));
  console.log(name);
}

async function main() {
  // Воспроизводимость: проект возвращаем к эталону до прогона.
  const reset = await fetch(`http://127.0.0.1:${serverPort}/api/reset`, {method:'POST'});
  if (!reset.ok) throw new Error('reset failed: ' + reset.status);
  let targets;
  for (let i = 0; i < 40; i++) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json`);
      if (response.ok) { targets = await response.json(); break; }
    } catch { /* Chrome is still starting. */ }
    await sleep(500);
  }
  if (!targets) throw new Error('Chrome CDP unavailable');
  socket = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve,reject) => {socket.onopen=resolve; socket.onerror=reject;});
  socket.onmessage = (event) => {
    const value = JSON.parse(event.data);
    const item = pending.get(value.id);
    if (!item) return;
    pending.delete(value.id);
    clearTimeout(item.timer);
    value.error ? item.reject(new Error(value.error.message)) : item.resolve(value.result);
  };
  await cdp('Page.enable');
  await cdp('Emulation.setDeviceMetricsOverride', {width:1600,height:900,deviceScaleFactor:1.2,mobile:false});
  await cdp('Page.navigate', {url});
  await waitFor(`document.getElementById('badges')?.textContent.includes('MCP')`, 30000);
  const report = {captured_at:new Date().toISOString(), url, screenshots:[],
    note:'Реальный прогон через веб-форму. Видео монтируется из настоящих снимков, ожидание модели сокращено.'};

  // Сцена «question»: выбираем готовый сценарий «Обновить CHANGELOG по коду».
  await evaluate(`[...document.querySelectorAll('#scenarios button')].find(b=>b.textContent.includes('CHANGELOG')).click(); document.getElementById('tools-panel').scrollIntoView({block:'end'}); window.scrollTo(0,0);`);
  await shot('short-question.png'); report.screenshots.push('short-question.png');

  // Запуск ассистента; сцена «steps» — живая трасса в процессе.
  await evaluate(`document.getElementById('run').click()`);
  await waitFor(`document.querySelectorAll('#steps .step').length >= 3`);
  await evaluate(`document.getElementById('trace-panel').scrollIntoView({block:'start'});`);
  await shot('short-steps.png'); report.screenshots.push('short-steps.png');

  // Ждём завершения прогона (реальные вызовы модели занимают время).
  await waitFor(`document.getElementById('status-line').textContent.includes('Готово') || document.getElementById('status-line').textContent.includes('ошибкой')`);
  const runId = await evaluate('window.lastRunId');
  const run = await (await fetch(`http://127.0.0.1:${serverPort}/api/runs/${runId}`)).json();
  report.run = run;
  if (run.status !== 'done') throw new Error('Run failed: ' + run.error);

  // Сцена «write»: раскрываем УСПЕШНЫЙ шаг записи файла (аргументы + diff результата).
  await evaluate(`(() => {
    const cards=[...document.querySelectorAll('#steps .step')].filter(c=>(c.textContent.includes('replace_in_file')||c.textContent.includes('write_file'))&&!c.textContent.includes('ОШИБКА'));
    const card=cards[cards.length-1];
    if(card){card.id='write-step-card'; card.querySelectorAll('details').forEach(d=>d.open=true); card.scrollIntoView({block:'center'});}
  })()`);
  await shot('short-write.png'); report.screenshots.push('short-write.png');
  await focusShot('short-write-focus.png', '#write-step-card');

  // Сцена «result»: финальный ответ и session_diff.
  await evaluate(`document.getElementById('answer-panel').scrollIntoView({block:'start'});`);
  await shot('short-result.png'); report.screenshots.push('short-result.png');
  await evaluate(`document.getElementById('diff-panel').scrollIntoView({block:'start'});`);
  await shot('short-diff.png'); report.screenshots.push('short-diff.png');
  await focusShot('short-diff-focus.png', '#diff-panel');

  writeFileSync(path.join(OUT, 'browser-demo.json'), JSON.stringify(report, null, 2));
  console.log('Saved real browser evidence');
}
try {await main();} finally {socket?.close(); chrome.kill();}
