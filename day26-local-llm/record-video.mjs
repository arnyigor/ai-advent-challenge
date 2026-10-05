// Запись демо Дня 26: настоящий Chrome, настоящие страницы, настоящие ответы Strata.
// Каждый кадр получает фактическую длительность показа, поэтому видео идёт в реальном
// времени: ожидание генерации не ускоряется и не подменяется заготовками.
// Запуск (стенд уже поднят): node day26-local-llm/record-video.mjs [report.html]
// Требования: Chrome, ffmpeg (пути через CHROME_PATH и FFMPEG_PATH).
import {spawn, execFileSync} from 'node:child_process';
import {writeFileSync, existsSync, readdirSync, mkdirSync, rmSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const FRAMES = path.join(root, 'video-frames');
const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const FFMPEG = process.env.FFMPEG_PATH || 'ffmpeg';
const PORT = Number(process.env.CDP_PORT || 9226);
const BOOT = process.env.DAY26_UI || 'http://127.0.0.1:8788';
const STRATA = process.env.LOCAL_LLM_UI || 'http://127.0.0.1:8083';
const OUT = path.resolve(root, '..', 'ChallengeVideos', 'day26-demo.mp4');
const sleep = ms => new Promise(r => setTimeout(r, ms));

function newestReport() {
  if (process.argv[2]) return path.resolve(process.argv[2]);
  const base = path.join(root, 'results');
  return path.join(base, readdirSync(base).sort().at(-1), 'report.html');
}

rmSync(FRAMES, {recursive: true, force: true});
mkdirSync(FRAMES, {recursive: true});

const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, '--no-sandbox', '--hide-scrollbars',
  '--window-size=1600,900', '--force-device-scale-factor=1', 'about:blank'], {stdio: 'ignore'});

let ws, id = 0;
const pending = new Map();
const cdp = (method, params = {}) => new Promise((resolve, reject) => {
  const msgId = ++id;
  pending.set(msgId, {resolve, reject});
  ws.send(JSON.stringify({id: msgId, method, params}));
  setTimeout(() => {if (pending.has(msgId)) {pending.delete(msgId); reject(Error(`${method} timeout`));}}, 60000);
});
const ev = expr => cdp('Runtime.evaluate', {expression: expr, returnByValue: true, awaitPromise: true}).then(r => r.result.value);
const problems = [];

// камера: Page.startScreencast сам отдаёт кадры с метками времени браузера.
// Из этих меток строится таймлайн, поэтому видео идёт в реальном времени.
const shots = [];
function cameraFrame(data, ts) {
  shots.push({file: `f${String(shots.length).padStart(5, '0')}.jpg`, ts, wall: Date.now(), data: Buffer.from(data, 'base64')});
}
async function cameraStart() {
  await cdp('Page.startScreencast', {format: 'jpeg', quality: 88, maxWidth: 1600, maxHeight: 900, everyNthFrame: 1});
}
const cameraStop = () => cdp('Page.stopScreencast').catch(() => {});

const marks = [];
const mark = (text) => marks.push({at: Date.now(), text});

async function open(url) {
  await cdp('Page.navigate', {url});
  for (let i = 0; i < 80; i++) {
    await sleep(250);
    if (await ev('document.readyState') === 'complete') return;
  }
  throw Error(`страница не загрузилась: ${url}`);
}

async function waitFor(expr, seconds, what) {
  for (let i = 0; i < seconds * 4; i++) {
    try {if (await ev(expr)) return true;} catch {}
    await sleep(250);
  }
  problems.push(`не дождались: ${what}`);
  return false;
}

async function click(selector) {await ev(`document.querySelector(${JSON.stringify(selector)})?.click()`);}

async function main() {
  const report = newestReport();
  if (!existsSync(report)) throw Error(`нет отчёта: ${report}`);
  console.log('✦ старт Chrome');
  let targets;
  for (let i = 0; i < 40; i++) {
    try {targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json(); break;} catch {await sleep(500);}
  }
  ws = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.method === 'Page.screencastFrame') {
      cameraFrame(m.params.data, m.params.metadata.timestamp);
      ws.send(JSON.stringify({id: ++id, method: 'Page.screencastFrameAck', params: {sessionId: m.params.sessionId}}));
      return;
    }
    if (m.id && pending.has(m.id)) {const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(Error(m.error.message)) : p.resolve(m.result);}
  };
  await cdp('Page.enable');
  await cdp('Runtime.enable');
  // Явный вьюпорт 1600×900: иначе кадры screencast выходят с полями окна Chrome.
  await cdp('Emulation.setDeviceMetricsOverride', {width: 1600, height: 900, deviceScaleFactor: 1, mobile: false});
  await cameraStart();

  // 1. Strata, Monitor: модель загружена, запросов ещё нет
  console.log('✦ Strata → Monitor');
  await open(STRATA);
  await click('#tab-btn-monitor');
  await waitFor(`document.getElementById('metrics')?.textContent.trim().length > 5`, 25, 'метрики Strata');
  await sleep(4500);
  const monitor = await ev("document.getElementById('metrics')?.innerText.split(String.fromCharCode(10)).join(' | ')");
  // Короткая подпись только из реально прочитанных значений.
  const pick = (re, text) => (String(text ?? '').match(re) || [])[1] ?? null;
  const gpu = pick(/\| (NVIDIA[^|]+?) \|/i, monitor);
  const vram = pick(/VRAM \| ([\d,]+\s*\/\s*\d+\s*GB)/i, monitor);
  const speed = pick(/Speed \| ([\d,]+t\/s)/i, monitor);
  // Общее число запросов до нашего прогона — по нему потом проверим, что наши три дошли.
  const countText = await ev("document.getElementById('req-all')?.innerText || ''");
  const before = Number((countText.match(/\d+/) || [NaN])[0]);
  console.log('   ', monitor.slice(0, 190), '| gpu:', gpu, '| vram:', vram);
  console.log('   всего запросов в Strata до прогона:', before);
  mark(`Strata на этой машине: ${gpu ?? 'GPU'} · VRAM ${vram ?? '—'} · ${speed ?? '—'} — модель загружена`);
  if (!/VRAM|GPU/i.test(monitor ?? '')) problems.push('метрики GPU/VRAM не прочитаны');
  if (!Number.isFinite(before)) problems.push('счётчик запросов Strata не прочитан');

  // 2. Strata, About: имя модели и движка
  console.log('✦ Strata → About');
  await click('#tab-btn-about');
  await waitFor(`document.getElementById('facts-engine')?.textContent.trim().length > 20`, 25, 'карточка модели');
  const facts = await ev(`document.getElementById('facts-engine')?.innerText.split(String.fromCharCode(10)).join(' · ')`);
  const modelId = pick(/Model · ([^·]+)/, facts);
  const engine = pick(/Engine · ([^·]+)/, facts);
  const experts = pick(/\((\d+,?\d* GB)\)/, facts);
  console.log('   ', facts);
  await sleep(6500);
  mark(`Модель ${modelId ?? '?'} · движок ${engine ?? '?'} · эксперты ${experts ?? '—'} в VRAM · контекст 204 800`);

  // 3. Стенд Дня 26: три запроса разной сложности
  console.log('✦ стенд Дня 26 → три запроса');
  await open(BOOT);
  await waitFor(`document.getElementById('run') && !document.getElementById('run').disabled`, 25, 'готовность стенда');
  await sleep(1500);
  mark('Клиент Дня 26: три запроса разной сложности уходят по HTTP на 127.0.0.1:8083');
  await click('#run');
  await waitFor(`document.querySelectorAll('#cards .card').length === 3 && !document.getElementById('run').disabled`, 240, 'все три ответа');
  const states = await ev(`[...document.querySelectorAll('#cards .card')].map(c => c.dataset.state).join(',')`);
  if (states !== 'done,done,done') {
    problems.push(`не все три запроса завершились ответом: ${states}`);
    mark('Часть запросов завершилась ошибкой — отчёт честно это фиксирует');
  }
  const times = await ev(`[...document.querySelectorAll('#cards .card .f')].map(f => (f.textContent.match(/^\\d+/) || ['?'])[0]).join(' / ')`);
  // Ссылку на отчёт читаем, пока стоим на странице стенда: дальше уходим в Strata.
  const reportHref = await ev("document.getElementById('report-link')?.href || ''");
  console.log('   состояния:', states, '| мс:', times);
  await sleep(3000);
  mark(states === 'done,done,done'
    ? `Три ответа получены за ${times} мс — простой, расчёт, код`
    : `Запросы завершены со статусом: ${states}. Время: ${times} мс`);

  // 4. Strata, Monitor: те же запросы в журнале модели
  console.log('✦ Strata → Monitor после запросов');
  await open(STRATA);
  await click('#tab-btn-monitor');
  await waitFor(`document.querySelectorAll('#req-body tr').length >= 3`, 30, 'журнал запросов Strata');
  const countAfterText = await ev("document.getElementById('req-all')?.innerText || document.getElementById('req-totals')?.innerText || ''");
  const after = Number((countAfterText.match(/\d+/) || [before + 3])[0]);
  await ev(`document.getElementById('req-all')?.click()`);
  await sleep(1500);
  // Длительности верхних строк должны совпасть с временем, которое показал клиент.
  const top = await ev("[...document.querySelectorAll('#req-body tr')].slice(0,3).map(r=>[...r.children].map(c=>c.innerText).join(' | ')).join(' ;; ')");
  const durations = (top || '').split(' ;; ').map(r => Number((r.split(' | ').at(-1) || '').replace(',', '.').replace(/[^\d.]/g, '')));
  console.log('   всего запросов после прогона:', after, '| длительности Strata, с:', durations.join(', '));
  const mine = times.split(' / ').map(Number).map(ms => ms / 1000).reverse();
  const matched = durations.length >= 3 && mine.every((s, i) => Math.abs(s - durations[i]) < 1.5);
  // Ожидается +3 от клиента и ещё +1 от вопроса в чате самой Strata (фаза 3).
  if (after - before < 3 || after - before > 4) problems.push(`журнал Strata вырос на ${after - before}, ожидалось 3–4`);
  if (!matched) problems.push('длительности в журнале Strata не совпали с временем клиента');
  await ev(`document.getElementById('req-wrap')?.scrollIntoView({block: 'start'})`);
  await sleep(8000);
  mark(matched
    ? `Журнал Strata: ${before} → ${after} записей, длительности ${durations.map(d => d.toFixed(1)).join(' / ')} с совпали с клиентом`
    : `Журнал Strata: ${before} → ${after} записей; длительности ${durations.join(' / ')} с`);

  console.log('✦ отчёт этого прогона');
  const reportUrl = String(reportHref || '').startsWith('http') ? reportHref : null;
  if (reportUrl) {
    await open(reportUrl);
    await waitFor("location.pathname.indexOf('/report/') === 0", 30, 'страница отчёта этого прогона');
  } else {
    problems.push('стенд не сохранил отчёт своего прогона');
    await open('file:///' + report.split(String.fromCharCode(92)).join('/'));
  }
  await sleep(3000);
  mark('Отчёт этого прогона: endpoint, время, модель ответа, usage');
  for (const n of [1, 2, 3]) {
    await ev(`(() => { const a = document.querySelectorAll('article')[${n}]; if (a) window.scrollTo(0, a.offsetTop + 120); else window.scrollTo(0, document.documentElement.scrollHeight); })()`);
    await sleep(3500);
  }
  // Конец третьего ответа: код и примеры — тоже показываем.
  await ev(`window.scrollTo(0, document.documentElement.scrollHeight)`);
  await sleep(3500);

  await cameraStop();
  await sleep(400);
  ws.close();
  chrome.kill();
  if (shots.length < 10) throw Error(`слишком мало кадров: ${shots.length}`);
  // Таймлайн строим по часам съёмки (Date.now), а не по меткам кадров браузера:
  // метки screencast измеренно отстают от реального времени — из-за этого видео обрезалось.
  const t0 = shots[0].wall;
  const tail = 2.0;
  const lastMark = marks.at(-1)?.at ?? shots.at(-1).wall;
  const totalSeconds = (Math.max(lastMark + tail * 1000, shots.at(-1).wall) - t0) / 1000;
  console.log(`✦ кадров: ${shots.length}, реальная длительность: ${totalSeconds.toFixed(1)} с`);

  for (const s of shots) writeFileSync(path.join(FRAMES, s.file), s.data);
  const list = shots.map((s, i) => {
    const until = i + 1 < shots.length ? shots[i + 1].wall : (t0 + (totalSeconds + tail) * 1000);
    return `file '${s.file}'\nduration ${Math.max(0.04, (until - s.wall) / 1000).toFixed(3)}`;
  }).join('\n') + `\nfile '${shots.at(-1).file}'\n`;
  writeFileSync(path.join(FRAMES, 'frames.txt'), list, 'utf8');

  const stamp = t => {
    const ms = Math.max(0, Math.round(t * 1000));
    const p = (n, w = 2) => String(n).padStart(w, '0');
    return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)},${p(ms % 1000, 3)}`;
  };
  const srt = marks.map((m, i) => {
    const from = (m.at - t0) / 1000;
    const until = ((marks[i + 1]?.at ?? t0 + totalSeconds * 1000) - t0) / 1000;
    return `${i + 1}\n${stamp(from)} --> ${stamp(Math.min(Math.max(until, from + 0.5), totalSeconds))}\n${m.text}\n`;
  }).join('\n');
  writeFileSync(path.join(FRAMES, 'captions.srt'), srt, 'utf8');

  mkdirSync(path.dirname(OUT), {recursive: true});
  const seconds = totalSeconds;
  console.log('✦ сборка mp4');
  execFileSync(FFMPEG, ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', 'frames.txt',
    '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000',
    '-vf', "scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=25,subtitles=captions.srt:force_style='FontName=Segoe UI,FontSize=15,Outline=2,Shadow=1,MarginV=14'",
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
    '-t', seconds.toFixed(3), '-movflags', '+faststart', OUT], {cwd: FRAMES, stdio: 'inherit'});
  console.log(`✓ ${OUT} (${seconds.toFixed(1)} с)`);
  if (problems.length) {console.error('предупреждения:', problems.join('; ')); process.exitCode = 1;}
}

main().catch(error => {console.error('Ошибка:', error.message); try {chrome.kill();} catch {} process.exit(1);});
