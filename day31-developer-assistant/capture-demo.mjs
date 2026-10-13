// Real browser interaction through CDP. No canned model responses.
import {spawn} from 'node:child_process';
import {existsSync, mkdirSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const DAY = path.dirname(fileURLToPath(import.meta.url));
const SHORT = process.env.DAY31_SHORT_DEMO === '1';
const OUT = path.join(DAY, 'evidence');
const FRAMES = path.join(DAY, 'video-frames');
mkdirSync(OUT, {recursive: true});
mkdirSync(FRAMES, {recursive: true});
const chromePath = process.env.CHROME_PATH || [process.env.PROGRAMFILES, process.env['PROGRAMFILES(X86)'], process.env.LOCALAPPDATA]
  .filter(Boolean).map((p) => path.join(p, 'Google', 'Chrome', 'Application', 'chrome.exe')).find(existsSync);
if (!chromePath) throw new Error('Set CHROME_PATH');
const port = Number(process.env.DAY31_CDP_PORT || 9231);
const url = process.env.DAY31_DEMO_URL || `http://127.0.0.1:${process.env.DAY31_WEB_PORT || 8796}/`;
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
async function waitFor(expression, timeout=200000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (await evaluate(expression)) return;
    await sleep(300);
  }
  throw new Error(`Browser timeout: ${expression}`);
}
async function shot(name) {
  if (SHORT) name = {'ui-00-ready.png':'short-ready.png', 'ui-01-pending.png':'short-question.png',
    'ui-2-answer.png':'short-answer.png', 'ui-source.png':'short-source.png', 'ui-mcp.png':'short-mcp.png'}[name] || name;
  await sleep(300);
  const {data} = await cdp('Page.captureScreenshot', {format:'png'});
  writeFileSync(path.join(OUT, name), Buffer.from(data, 'base64'));
  console.log(name);
}
async function focusShot(name, selector) {
  const clip = await evaluate(`(() => {const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height,scale:1};})()`);
  const {data}=await cdp('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip});
  writeFileSync(path.join(OUT,name),Buffer.from(data,'base64'));
}

async function main() {
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
  await waitFor(`document.getElementById('config')?.textContent.includes('чанков')`, 20000);
  await shot('ui-00-ready.png');
  const report = {captured_at:new Date().toISOString(), url, turns:[], screenshots:['ui-00-ready.png'],
    note:'Реальные запросы через веб-форму. Видео монтируется из настоящих снимков, ожидание сокращено.'};
  const commands = SHORT ? [
    '/help Где находятся документация, RAG и MCP? Какая текущая git-ветка? Ответь четырьмя короткими пунктами.'
  ] : [
    '/help Как устроен проект и где находятся RAG и MCP?',
    '/help Как проходит запрос /help и какие поля возвращает API?',
    '/help Какая сейчас git-ветка проекта?',
    '/help Какова выручка проекта за 2025 год?',
  ];
  for (let i=0;i<commands.length;i++) {
    console.log(commands[i]);
    await evaluate(`window.scrollTo(0,0); document.getElementById('mcp-details').open=false; document.getElementById('command').value=${JSON.stringify(commands[i])}; document.getElementById('form').requestSubmit();`);
    await waitFor(`document.getElementById('submit').disabled`, 10000);
    if (i===0) { await shot('ui-01-pending.png'); report.screenshots.push('ui-01-pending.png'); }
    await waitFor(`!document.getElementById('submit').disabled`);
    const result = await evaluate('window.lastResult');
    if (!result) throw new Error(await evaluate(`document.getElementById('answer').textContent`));
    const name = `ui-${i+2}-answer.png`;
    await evaluate(`document.querySelector('.input').scrollIntoView({block:'start'});`);
    await shot(name);
    if (SHORT) await focusShot('short-answer-focus.png','.answer');
    report.screenshots.push(name);
    report.turns.push({command:commands[i],...result});
    if (i===0) {
      await evaluate(`const d=${SHORT ? "[...document.querySelectorAll('#sources details')].find(d=>d.textContent.includes('Где находятся RAG и MCP')) || document.querySelector('#sources details')" : "document.querySelector('#sources details')"}; d.open=true; d.scrollIntoView({block:'center'});`);
      await shot('ui-source.png'); report.screenshots.push('ui-source.png');
      if (SHORT) await focusShot('short-source-focus.png','#sources details[open]');
      await evaluate(`const m=document.getElementById('mcp-details'); m.open=true; m.scrollIntoView({block:'center'});`);
      await shot('ui-mcp.png'); report.screenshots.push('ui-mcp.png');
      if (SHORT) await focusShot('short-mcp-focus.png','#mcp-details');
    }
    writeFileSync(path.join(OUT, SHORT ? 'short-browser-demo.json' : 'browser-demo.json'), JSON.stringify(report,null,2));
  }
  console.log('Saved real browser evidence');
}
try {await main();} finally {socket?.close(); chrome.kill();}
