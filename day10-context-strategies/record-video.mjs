#!/usr/bin/env node
// Records a UI walkthrough of all three strategies from the real comparison run.
import {spawn, spawnSync} from 'node:child_process';
import {mkdirSync, mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const dayDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(dayDir, '..');
const result = JSON.parse(readFileSync(path.join(dayDir, 'results', 'strategies.json'), 'utf8'));
const framesDir = mkdtempSync(path.join(os.tmpdir(), 'day10-video-frames-'));
const userDataDir = mkdtempSync(path.join(os.tmpdir(), 'day10-video-chrome-'));
const port = Number(process.env.DAY10_WEB_PORT || 8010);
const cdpPort = Number(process.env.DAY10_CDP_PORT || 9270);
const chromePath = process.env.CHROME_PATH || path.join(process.env.ProgramFiles || '', 'Google', 'Chrome', 'Application', 'chrome.exe');
const ffmpegPath = process.env.FFMPEG_PATH || 'ffmpeg';
const pythonPath = process.env.PYTHON_PATH || 'python';
const output = process.argv.includes('--out')
  ? path.resolve(process.argv[process.argv.indexOf('--out') + 1])
  : path.resolve(rootDir, 'ChallengeVideos', 'day10-demo.mp4');
mkdirSync(path.dirname(output), {recursive: true});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const server = spawn(pythonPath, ['web_server.py', '--port', String(port)], {cwd: dayDir, stdio: 'ignore'});
const chrome = spawn(chromePath, [
  '--headless=new', `--remote-debugging-port=${cdpPort}`, '--no-sandbox',
  `--user-data-dir=${userDataDir}`, '--disable-gpu', '--window-size=1440,1000',
  '--hide-scrollbars', 'about:blank',
], {stdio: 'ignore'});

async function waitJson(url, attempts = 80) {
  for (let index = 0; index < attempts; index++) {
    try { const response = await fetch(url); if (response.ok) return response.json(); } catch {}
    await sleep(250);
  }
  throw new Error(`Не дождался ${url}`);
}

let socket;
let callId = 0;
const pending = new Map();
function cdp(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++callId;
    pending.set(id, {resolve, reject});
    socket.send(JSON.stringify({id, method, params}));
  });
}
const evaluate = (expression) => cdp('Runtime.evaluate', {expression, returnByValue: true}).then((value) => {
  if (value.exceptionDetails) throw new Error(value.exceptionDetails.text);
  return value.result.value;
});

let recording = true;
let frame = 0;
async function camera() {
  while (recording) {
    const {data} = await cdp('Page.captureScreenshot', {format: 'png', optimizeForSpeed: true});
    writeFileSync(path.join(framesDir, `f${String(frame++).padStart(5, '0')}.png`), Buffer.from(data, 'base64'));
    await sleep(125);
  }
}

const captionScript = (caption) => `(() => {
  let bar = document.getElementById('videoCaption');
  if (!bar) {
    bar = document.createElement('div'); bar.id = 'videoCaption';
    bar.style.cssText = 'position:fixed;left:0;right:320px;top:73px;z-index:9999;background:#030712f2;color:#f5d76e;border-bottom:1px solid #334155;padding:12px;text-align:center;font:700 16px Segoe UI';
    document.body.appendChild(bar);
    const transcript = document.getElementById('msgsInner');
    if (transcript) transcript.style.paddingTop = '68px';
  }
  bar.textContent = ${JSON.stringify(caption)};
})()`;

async function scene(caption, action = null, duration = 3600) {
  if (action) await evaluate(action);
  await evaluate(captionScript(caption));
  await sleep(duration);
}

// Реальные реплики берём из БД прогона: подставлять текст руками нельзя.
const dumpScript = `
import json, sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
messages = conn.execute(
    "select session_id, branch_id, role, content from messages order by rowid"
).fetchall()
# Расход берём из request_log: у стратегии facts на ход приходится два вызова,
# и второй (память) не виден в per-turn usage результата прогона.
calls = conn.execute(
    "select session_id, status, usage_json from request_log order by created_at, rowid"
).fetchall()
print(json.dumps({
    "messages": [{"session": s, "branch": b, "role": r, "content": c} for s, b, r, c in messages],
    "calls": [{"session": s, "status": st, "usage": json.loads(u)} for s, st, u in calls],
}, ensure_ascii=False))
`;
const dumped = spawnSync(pythonPath, ['-c', dumpScript, path.join(dayDir, 'strategies.db')], {
  encoding: 'utf8', env: {...process.env, PYTHONIOENCODING: 'utf-8'},
});
if (dumped.status !== 0) throw new Error(`Не смог прочитать transcript: ${dumped.stderr}`);
const dump = JSON.parse(dumped.stdout);
const transcriptOf = (session, branch = null) => dump.messages.filter(
  (row) => row.session === session && (branch === null || row.branch === branch),
);
// Счётчик сессии для одной стратегии: вызовы идут в том же порядке, что ходы.
function billing(session) {
  const queue = dump.calls.filter((row) => row.session === session);
  const total = {input: 0, output: 0, calls: 0};
  return {
    // Один ход = все служебные вызовы памяти плюс сам ответ.
    turn() {
      let row;
      do {
        row = queue.shift();
        if (!row) break;
        total.input += row.usage.input_tokens || 0;
        total.output += row.usage.output_tokens || 0;
        total.calls += 1;
      } while (row.status !== 'ok');
      return {
        sessInput: ru(total.input), sessOutput: ru(total.output),
        sessTotal: ru(total.input + total.output), sessCalls: String(total.calls),
      };
    },
    total,
  };
}

const helpersScript = `(() => {
  const inner = document.getElementById('msgsInner');
  const set = (id, value) => { const node = document.getElementById(id); if (node) node.textContent = String(value); };
  window.__demo = {
    clear() { inner.innerHTML = ''; },
    push(role, text) {
      const node = document.createElement('div');
      node.className = 'msg ' + role;
      node.innerHTML = '<div class="bubble"></div>';
      node.firstChild.textContent = text;
      inner.appendChild(node);
      const box = document.getElementById('msgs');
      box.scrollTop = box.scrollHeight;
    },
    metrics(values) { for (const [id, value] of Object.entries(values)) set(id, value); },
    strategy(id, label, hint) {
      document.getElementById('strategySelect').value = id;
      set('strategyBadge', label);
      set('strategyHint', hint);
    },
    facts(values) {
      const keys = Object.keys(values);
      set('factsCount', keys.length);
      document.getElementById('factsBox').innerHTML = keys.length
        ? keys.map((key) => '<div class="fact"><b>' + key + '</b><span>' + values[key] + '</span></div>').join('')
        : 'Пусто.';
    },
    branches(list, active) {
      document.getElementById('branchList').innerHTML = list.map((item) =>
        '<button type="button" class="branch' + (item.id === active ? ' active' : '') + '"><b>' + item.id
        + '</b><small>' + item.count + ' сообщ.' + (item.origin || '') + '</small></button>').join('');
    },
  };
})()`;

function turnScript(user, assistant, metrics) {
  return `(() => {
    window.__demo.push('user', ${JSON.stringify(user)});
    window.__demo.push('assistant', ${JSON.stringify(assistant)});
    window.__demo.metrics(${JSON.stringify(metrics)});
  })()`;
}

const approx = (value) => `≈${Number(value).toLocaleString('ru-RU')}`;
const ru = (value) => Number(value).toLocaleString('ru-RU');
const byName = (name) => result.strategies.find((item) => item.strategy === name);

// Один проход по стратегии: пять ходов с фактами, затем контрольные вопросы.
async function playStrategy(name, {hint, factTurnCaptions, skipCaption, probeCaption, verdict}) {
  const data = byName(name);
  if (!data) return;
  const messages = transcriptOf(`day10-${name}`);
  const bill = billing(`day10-${name}`);
  const session = bill.total;
  const factsOf = (turn) => turn.facts_after_turn || {};

  await scene(`Стратегия ${data.label}: ${hint}`, `(() => {
    window.__demo.clear();
    window.__demo.strategy(${JSON.stringify(name)}, ${JSON.stringify(data.label)}, ${JSON.stringify(hint)});
    window.__demo.facts({});
    window.__demo.metrics({fullTokens: '—', effectiveTokens: '—', savedTokens: '≈0',
      droppedCount: '0', verbatimCount: '0', sessInput: '0', sessOutput: '0', sessTotal: '0', sessCalls: '0'});
  })()`, 4200);

  for (let index = 0; index < 5; index++) {
    const turn = data.setup_turns[index];
    if (name === 'facts') {
      await evaluate(`window.__demo.facts(${JSON.stringify(factsOf(turn))})`);
    }
    await scene(factTurnCaptions[index], turnScript(
      messages[index * 2].content, messages[index * 2 + 1].content,
      {
        fullTokens: approx(turn.request_tokens_estimate),
        effectiveTokens: approx(turn.request_tokens_estimate),
        droppedCount: String(turn.dropped_message_count),
        verbatimCount: String(turn.verbatim_message_count),
        ...bill.turn(),
      },
    ), 2400);
  }

  // Остальные setup-ходы прокручиваем разом: они нейтральные, но вытесняют факты.
  const rest = data.setup_turns.slice(5);
  const restScript = rest.map((turn, offset) => {
    const base = (5 + offset) * 2;
    return `window.__demo.push('user', ${JSON.stringify(messages[base].content)});
      window.__demo.push('assistant', ${JSON.stringify(messages[base + 1].content)});`;
  }).join('\n');
  const last = data.setup_turns[data.setup_turns.length - 1];
  for (let index = 0; index < rest.length; index++) bill.turn();
  if (name === 'facts') {
    await evaluate(`window.__demo.facts(${JSON.stringify(factsOf(last))})`);
  }
  await scene(skipCaption, `(() => {
    ${restScript}
    window.__demo.metrics(${JSON.stringify({
      fullTokens: approx(last.request_tokens_estimate),
      effectiveTokens: approx(last.request_tokens_estimate),
      droppedCount: String(last.dropped_message_count),
      verbatimCount: String(last.verbatim_message_count),
      sessInput: ru(session.input), sessOutput: ru(session.output),
      sessTotal: ru(session.input + session.output), sessCalls: String(session.calls),
    })});
    const box = document.getElementById('msgs'); box.scrollTop = box.scrollHeight;
  })()`, 4200);

  await scene(probeCaption, null, 3000);
  for (const probe of data.probes) {
    await scene(
      `${probe.passed ? '✓' : '✗'} ${probe.question}`,
      turnScript(probe.question, probe.answer, bill.turn()),
      probe === data.probes[0] ? 3400 : 2000,
    );
  }
  if (session.input !== data.total_input_tokens || session.calls !== data.api_calls) {
    throw new Error(`Метрики ${name} разошлись с прогоном: ${session.input}/${session.calls} vs ${data.total_input_tokens}/${data.api_calls}`);
  }
  await scene(verdict(data), null, 4600);
}

async function playBranching() {
  const demo = result.branching_demo;
  if (!demo) return;
  const checkpoint = demo.checkpoint_messages;
  const main = transcriptOf('day10-branchdemo', 'main');
  await scene('Стратегия Branching: ветки диалога от одной точки', `(() => {
    window.__demo.clear();
    window.__demo.strategy('branching', 'Branching', 'Вся история активной ветки.');
    window.__demo.branches([{id: 'main', count: ${checkpoint}}], 'main');
    window.__demo.facts({});
    // Плитки предыдущей стратегии здесь не значат ничего — обнуляем.
    window.__demo.metrics({droppedCount: '0', verbatimCount: '${checkpoint}',
      fullTokens: '—', effectiveTokens: '—', savedTokens: '≈0',
      sessInput: '0', sessOutput: '0', sessTotal: '0', sessCalls: '0'});
    document.getElementById('branchList').scrollIntoView({block: 'center'});
    ${main.map((row) => `window.__demo.push(${JSON.stringify(row.role)}, ${JSON.stringify(row.content)});`).join('\n')}
  })()`, 4200);
  await scene(`Checkpoint: ${checkpoint} сообщений общей части ТЗ`, null, 3200);

  const names = Object.keys(demo.branches);
  const list = [
    {id: 'main', count: checkpoint},
    ...names.map((id) => ({id, count: demo.branches[id].message_count, origin: ` ← main@${demo.branches[id].fork_index}`})),
  ];
  const captions = {
    [names[0]]: 'Ветка A продолжает тот же ТЗ своим решением',
    [names[1]]: 'Ветка B — альтернативное решение от той же точки',
  };
  for (const id of names) {
    const branch = transcriptOf('day10-branchdemo', id);
    await scene(captions[id], `(() => {
      window.__demo.clear();
      window.__demo.branches(${JSON.stringify(list)}, ${JSON.stringify(id)});
      window.__demo.metrics({verbatimCount: '${demo.branches[id].message_count}', droppedCount: '0'});
      document.getElementById('branchList').scrollIntoView({block: 'center'});
      ${main.map((row) => `window.__demo.push(${JSON.stringify(row.role)}, ${JSON.stringify(row.content)});`).join('\n')}
      ${branch.map((row) => `window.__demo.push(${JSON.stringify(row.role)}, ${JSON.stringify(row.content)});`).join('\n')}
    })()`, 4600);
  }
  const answers = names.map((id) => `${id}: «${demo.branches[id].answer.trim()}»`).join(' · ');
  await scene(`Переключаемся между ветками — каждая помнит только своё решение. ${answers}`, null, 5200);
  await scene(
    demo.isolated
      ? 'Общий префикс одинаков, чужих сообщений не видит ни одна ветка'
      : 'Внимание: ветки не изолированы — смотри results/strategies.json',
    null, 4200,
  );
}

async function main() {
  await waitJson(`http://127.0.0.1:${port}/api/config`);
  const targets = await waitJson(`http://127.0.0.1:${cdpPort}/json`);
  socket = new WebSocket(targets.find((target) => target.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve) => { socket.onopen = resolve; });
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const callbacks = pending.get(message.id); pending.delete(message.id);
    message.error ? callbacks.reject(new Error(message.error.message)) : callbacks.resolve(message.result);
  };
  await cdp('Page.enable');
  await cdp('Runtime.enable');
  await cdp('Page.navigate', {url: `http://127.0.0.1:${port}/`});
  await sleep(1800);
  await evaluate(helpersScript);
  await evaluate(captionScript('День 10 · Один сценарий «собираем ТЗ» — три стратегии управления контекстом, без summary'));
  const cameraPromise = camera();
  await sleep(3600);

  const factCaptions = [
    'Ход 1 — код проекта Ирбис-4',
    'Ход 2 — платформа Android',
    'Ход 3 — бюджет 640 000 ₽',
    'Ход 4 — срок 15 декабря',
    'Ход 5 — отчёт в PDF',
  ];
  await playStrategy('sliding', {
    hint: 'только последние 6 сообщений, остальное отбрасывается',
    factTurnCaptions: factCaptions,
    skipCaption: 'Ходы 6–12 нейтральные — и они вытесняют из окна все пять фактов',
    probeCaption: 'Пять контрольных вопросов о фактах, которые уже отброшены',
    verdict: (data) => `Sliding Window: ${data.correct_probes}/${data.total_probes} — окно не забывает частично, оно отбрасывает начисто. ${ru(data.total_input_tokens)} входных токенов`,
  });

  await playStrategy('facts', {
    hint: 'блок «ключ: значение» + последние 6 сообщений',
    factTurnCaptions: factCaptions.map((caption) => `${caption} — уходит в блок facts`),
    skipCaption: 'Те же нейтральные ходы: сообщения вытеснены, но facts остались',
    probeCaption: 'Те же пять вопросов — теперь отвечает память, а не история',
    verdict: (data) => `Sticky Facts: ${data.correct_probes}/${data.total_probes}, но ${ru(data.total_input_tokens)} входных токенов и ${data.api_calls} вызовов — каждая реплика стоит двух запросов`,
  });

  await playBranching();

  const rows = result.strategies.map((item) =>
    `${item.label}: ${item.correct_probes}/${item.total_probes}, ${ru(item.total_input_tokens)} вход, ${item.api_calls} вызовов`).join(' · ');
  await scene('Один сценарий, один провайдер, одна модель — сравниваем честно', "document.getElementById('comparison').scrollIntoView({block:'center'})", 4200);
  await scene(rows, null, 6400);
  await scene('Окно дешевле всех и теряет всё. Facts держат качество, но платят вторым вызовом. Ветка ничего не теряет, пока влезает в контекст', null, 6000);
  await scene('Код: strategies.py · agent.py · history_store.py · run_strategies.py', null, 4200);

  recording = false;
  await cameraPromise;
  const captureFps = 8;
  const encoded = spawnSync(ffmpegPath, [
    '-y', '-framerate', String(captureFps), '-i', path.join(framesDir, 'f%05d.png'),
    '-vf', 'fps=24,scale=trunc(iw/2)*2:trunc(ih/2)*2', '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p', '-crf', '23', output,
  ], {stdio: 'inherit'});
  if (encoded.status !== 0) throw new Error('ffmpeg завершился с ошибкой');
  console.log(`Видео: ${output}`);
}

try {
  await main();
} finally {
  recording = false;
  try { socket?.close(); } catch {}
  try { chrome.kill(); } catch {}
  try { server.kill(); } catch {}
}
