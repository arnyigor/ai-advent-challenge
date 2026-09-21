// Records real CLI execution using the repository's Chrome CDP + ffmpeg approach.
import {spawn, spawnSync} from 'node:child_process';
import {existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';

const day = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(day, '..');
const localPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const python = process.env.PYTHON_PATH || (existsSync(localPython) ? localPython : 'python');
const command = JSON.parse(process.env.MCP_DEMO_COMMAND || '[]');
const output = path.join(root, 'ChallengeVideos', 'day16-cli-demo.mp4');
const framesRoot = path.join(day, 'video-frames');
mkdirSync(framesRoot, {recursive:true});
mkdirSync(path.dirname(output), {recursive:true});
const frames = mkdtempSync(path.join(framesRoot, 'run-'));
const profile = mkdtempSync(path.join(os.tmpdir(), 'day16-chrome-'));
const chromePath = process.env.CHROME_PATH || path.join(process.env.ProgramFiles || '', 'Google/Chrome/Application/chrome.exe');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const port = await new Promise((resolve, reject) => {
  const listener = net.createServer();
  listener.on('error', reject);
  listener.listen(0, '127.0.0.1', () => { const port = listener.address().port; listener.close(() => resolve(port)); });
});
const chrome = spawn(chromePath, ['--headless=new', `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`, '--window-size=1440,1000', '--hide-scrollbars', 'about:blank'],
  {stdio:'ignore', windowsHide:true});
let chromeError;
chrome.on('error', error => { chromeError = error; });
let ws, recording = false, cameraJob, cameraError, frame = 0, nextId = 0;
const pending = new Map();
function cdp(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
    pending.set(id, {resolve, reject, timer});
    ws.send(JSON.stringify({id, method, params}));
  });
}
async function evaluate(expression) {
  const result = await cdp('Runtime.evaluate', {expression, returnByValue:true});
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}
async function show(title, subtitle, body, badge = 'DAY 16 / MCP') {
  await evaluate(`(() => {
    document.querySelector('h1').textContent=${JSON.stringify(title)};
    document.querySelector('p').textContent=${JSON.stringify(subtitle)};
    document.querySelector('pre').textContent=${JSON.stringify(body)};
    document.querySelector('aside').textContent=${JSON.stringify(badge)};
  })()`);
}
async function camera() {
  while (recording) {
    const start = Date.now();
    const {data} = await cdp('Page.captureScreenshot', {format:'png'});
    writeFileSync(path.join(frames, `f${String(frame++).padStart(5, '0')}.png`), Buffer.from(data, 'base64'));
    await sleep(Math.max(0, 200 - (Date.now() - start)));
  }
}
function run(args, cwd = day) {
  return new Promise((resolve, reject) => {
    const child = spawn(python, args, {cwd, windowsHide:true, env:{...process.env, PYTHONUTF8:'1'}});
    let stdout = '', stderr = '';
    const timer = setTimeout(() => { child.kill(); reject(new Error('Process timeout')); }, 120000);
    child.stdout.on('data', data => { stdout += data.toString('utf8'); });
    child.stderr.on('data', data => { stderr += data.toString('utf8'); });
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('close', code => { clearTimeout(timer); resolve({code, stdout, stderr}); });
  });
}
try {
  let pages;
  for (let attempt = 0; attempt < 120; attempt++) {
    if (chromeError) throw chromeError;
    try { pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); break; } catch { await sleep(250); }
  }
  if (!pages) throw new Error('Chrome did not start');
  ws = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  ws.onmessage = event => {
    const message = JSON.parse(event.data), callback = pending.get(message.id);
    if (!callback) return;
    pending.delete(message.id); clearTimeout(callback.timer);
    message.error ? callback.reject(new Error(message.error.message)) : callback.resolve(message.result);
  };
  await cdp('Page.enable');
  await cdp('Emulation.setDeviceMetricsOverride', {width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  const {frameTree} = await cdp('Page.getFrameTree');
  await cdp('Page.setDocumentContent', {frameId:frameTree.frame.id, html:`<!doctype html><meta charset="utf-8">
    <style>*{box-sizing:border-box}body{margin:0;padding:52px 64px;background:#0c1420;color:#edf4ff;font-family:Segoe UI,sans-serif}
    aside{color:#6ce7cc;font-size:20px;letter-spacing:3px}h1{font-size:40px;margin:20px 0 12px}p{font-size:23px;color:#afc1d8;margin:0 0 30px}
    pre{font:21px/1.55 Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;background:#131f30;border:1px solid #354861;border-radius:16px;padding:28px;margin:0;max-height:735px;overflow:hidden}
    footer{position:fixed;bottom:18px;color:#829ab7;font-size:16px}</style>
    <aside></aside><h1></h1><p></p><pre></pre><footer>AI Advent Challenge · Реальные процессы Python · initialize → tools/list → закрытие сессии</footer>`});
  recording = true;
  cameraJob = camera().catch(error => { cameraError = error; recording = false; });
  await show('День 16. Подключение MCP', 'Python-клиент получает инструменты существующего MCP-сервера.',
    'Клиент                         MCP-сервер\n\n  initialize ───────────────────►\n             ◄── сервер, протокол\n\n  tools/list ───────────────────►\n             ◄── имена, описания, JSON Schema\n\n  Закрытие сессии\n\nТранспорт: stdio. Инструменты только перечисляются.');
  await sleep(6500);
  const source = readFileSync(path.join(day, 'mcp_client.py'), 'utf8');
  const core = source.slice(source.indexOf('    async with asyncio.timeout'), source.indexOf('                    if cursor is None:'))
    .split('\n').map(line => line.startsWith('    ') ? line.slice(4) : line).join('\n');
  await show('Код соединения', 'ClientSession из официального SDK: handshake и получение каталога.', core);
  await sleep(9000);
  const cliArgs = ['mcp_client.py', '--timeout', '60', '--json', ...(command.length ? ['--command', ...command] : [])];
  const displayedCommand = 'python mcp_client.py --timeout 60 --json' + (command.length ? '\n  --command <Python вашего MCP> <server.py>' : '');
  await show('Запуск клиента', 'Выполняется настоящий CLI; результат будет получен по MCP.', '$ ' + displayedCommand + '\n\nПодключение…');
  const actual = await run(cliArgs);
  if (actual.code !== 0) throw new Error(actual.stderr);
  const result = JSON.parse(actual.stdout);
  if (result.handshake !== 'ok' || !result.tools.length || !result.sessionClosed) throw new Error('Discovery validation failed');
  writeFileSync(path.join(frames, 'discovery.json'), actual.stdout);
  await show('Соединение установлено', 'initialize вернул сведения сервера; tools/list вернул каталог.',
    `$ ${displayedCommand}\n\nMCP handshake: ${result.handshake}\nServer: ${result.server.name}\nProtocol: ${result.protocolVersion}\nTransport: ${result.transport}\nAvailable tools: ${result.tools.length}\nSession closed: ${result.sessionClosed}`, 'HANDSHAKE / OK');
  await sleep(7000);
  const names = result.tools.map(tool => tool.name);
  for (let offset = 0; offset < names.length; offset += 16) {
    await show('Доступные инструменты', `Сервер ${result.server.name} · ${names.length} инструментов · список получен по MCP`,
      names.slice(offset, offset + 16).map((name, index) => `${String(offset + index + 1).padStart(2)}  ${name}`).join('\n'), 'TOOLS / LIST');
    await sleep(6500);
  }
  const tool = result.tools.find(tool => tool.name === 'list_directory') || result.tools[0];
  const schemaLines = ['{', `  "type": ${JSON.stringify(tool.inputSchema.type)},`,
    `  "required": ${JSON.stringify(tool.inputSchema.required || [])},`, '  "properties": {',
    Object.entries(tool.inputSchema.properties || {}).map(([key,value]) => `    ${JSON.stringify(key)}: ${JSON.stringify(value)}`).join(',\n'), '  }', '}'];
  await show('Схема инструмента', `${tool.name} · обязательные аргументы и типы получены от сервера`, schemaLines.join('\n'), 'INPUT / SCHEMA');
  await sleep(8000);
  await show('Проверки', 'Запускаем интеграционные тесты: реальные дочерние MCP-процессы.',
    '$ python -m pytest tests/test_day16_mcp_connection.py -q\n\nПроверяем handshake, каталог, повторное соединение,\nошибку запуска и таймаут…');
  const tests = await run(['-m', 'pytest', 'tests/test_day16_mcp_connection.py', '-q'], root);
  if (tests.code !== 0) throw new Error(tests.stdout + tests.stderr);
  await show('Проверки пройдены', 'Код и запись готовы к проверке.', tests.stdout.trim() + `\n\nРеальный сервер: ${result.server.name}\nПолучено инструментов: ${result.tools.length}\n\nЗапуск: python mcp_client.py\nСвой сервер: --command <программа> <аргументы>\nHTTP: --url <MCP endpoint>`, 'VERIFIED');
  await sleep(7000);
  recording = false; await cameraJob;
  if (cameraError) throw cameraError;
  const encoded = spawnSync(process.env.FFMPEG_PATH || 'ffmpeg', ['-y','-loglevel','error','-framerate','5',
    '-i',path.join(frames,'f%05d.png'),'-vf','fps=25','-c:v','libx264','-preset','veryfast','-threads','2','-pix_fmt','yuv420p','-crf','20','-movflags','+faststart',output], {stdio:'inherit',windowsHide:true});
  if (encoded.status !== 0) throw new Error('ffmpeg failed');
  console.log(JSON.stringify({output,frames,count:frame,server:result.server.name,tools:names.length}));
} finally {
  recording = false;
  if (cameraJob) await cameraJob;
  for (const callback of pending.values()) { clearTimeout(callback.timer); callback.reject(new Error('Recording ended')); }
  ws?.close(); chrome.kill();
}
