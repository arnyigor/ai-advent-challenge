/* День 34: живая трасса агентных шагов, опрос /api/runs/{id} раз в секунду. */
const $ = (id) => document.getElementById(id);
const state = { runId: null, timer: null, rendered: 0 };

function esc(text) { return document.createTextNode(String(text)); }

function badge(text) {
  const span = document.createElement('span');
  span.className = 'badge';
  span.appendChild(esc(text));
  return span;
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = 'HTTP ' + response.status;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

async function bootstrap() {
  const data = await api('/api/bootstrap');
  const badges = $('badges');
  badges.replaceChildren();
  badges.appendChild(badge('LLM: ' + data.provider + ':' + data.model));
  badges.appendChild(badge('MCP: ' + data.mcp.server + ' · ' + data.mcp.tools.length + ' инструментов'));
  badges.appendChild(badge('лимит: ' + data.max_steps + ' шагов'));
  if (!data.baseline_ok) badges.appendChild(badge('⚠ baseline не найден'));

  const tools = $('tools');
  tools.replaceChildren();
  for (const tool of data.mcp.tools) {
    const card = document.createElement('div');
    card.className = 'tool-card';
    const name = document.createElement('code');
    name.appendChild(esc(tool.name));
    const desc = document.createElement('p');
    desc.appendChild(esc(tool.description));
    card.append(name, desc);
    tools.appendChild(card);
  }

  const scenarios = $('scenarios');
  scenarios.replaceChildren();
  for (const scenario of data.scenarios) {
    const button = document.createElement('button');
    button.appendChild(esc(scenario.title));
    button.onclick = () => { $('goal').value = scenario.goal; $('goal').focus(); };
    scenarios.appendChild(button);
  }
}

function stepCard(step) {
  const card = document.createElement('div');
  card.className = 'step' + (step.action === 'final' ? ' final' : '') + (step.error ? ' error' : '');
  const head = document.createElement('div');
  head.className = 'head';
  const n = document.createElement('span');
  n.className = 'n';
  n.appendChild(esc('Шаг ' + step.n));
  head.appendChild(n);
  if (step.action === 'tool') {
    const tool = document.createElement('span');
    tool.className = 'tool';
    tool.appendChild(esc('🔧 ' + step.tool));
    head.appendChild(tool);
  } else {
    head.appendChild(badge('финальный ответ'));
  }
  const ms = document.createElement('span');
  ms.className = 'ms';
  ms.appendChild(esc((step.duration_ms / 1000).toFixed(1) + ' с'));
  head.appendChild(ms);
  card.appendChild(head);
  if (step.thought) {
    const thought = document.createElement('div');
    thought.className = 'thought';
    thought.appendChild(esc('💭 ' + step.thought));
    card.appendChild(thought);
  }
  if (step.action === 'tool') {
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.appendChild(esc('аргументы и результат'));
    details.appendChild(summary);
    const args = document.createElement('pre');
    args.appendChild(esc('АРГУМЕНТЫ\n' + JSON.stringify(step.arguments, null, 2)));
    details.appendChild(args);
    const result = document.createElement('pre');
    let payload = step.error ? 'ОШИБКА: ' + step.error
      : JSON.stringify(step.result, null, 2);
    if (!step.error && step.result) {
      if (step.tool === 'read_file') payload = step.result.path + '\n' + step.result.content;
      if (step.tool === 'search_files') payload = step.result.matches.map(
        m => m.path + ':' + m.line + '  ' + m.text).join('\n') || 'Совпадений нет';
      if (step.result.diff) payload = step.result.diff;
    }
    result.appendChild(esc('РЕЗУЛЬТАТ\n' +
      (payload.length > 3000 ? payload.slice(0, 3000) + '\n… (обрезано)' : payload)));
    details.appendChild(result);
    card.appendChild(details);
  }
  return card;
}

function renderRun(run) {
  window.currentRun = run;
  const stepsBox = $('steps');
  stepsBox.classList.remove('empty');
  const fresh = run.steps.slice(state.rendered);
  for (const step of fresh) stepsBox.appendChild(stepCard(step));
  state.rendered = run.steps.length;
  $('step-count').textContent = run.steps.length ? run.steps.length + ' шагов' : '';
  if (run.status === 'running') {
    $('status-line').innerHTML = '';
    const spinner = document.createElement('span');
    spinner.className = 'spinner';
    $('status-line').append(spinner, esc('Ассистент работает: модель выбирает инструменты, MCP исполняет…'));
  }
  if (run.status === 'done') {
    $('status-line').textContent = 'Готово: ' + run.tool_calls + ' вызовов инструментов, ' +
      (run.duration_ms / 1000).toFixed(1) + ' с, модель ' + run.model;
    $('answer-panel').classList.remove('hidden');
    $('answer').textContent = run.answer;
    $('diff-panel').classList.remove('hidden');
    const chips = $('changed-files');
    chips.replaceChildren();
    if (run.changed_files.length === 0) {
      $('diff').textContent = 'Файлы не изменялись (задача только на чтение).';
    } else {
      for (const file of run.changed_files) {
        const chip = document.createElement('span');
        chip.appendChild(esc(file));
        chips.appendChild(chip);
      }
      $('diff').textContent = run.diff || '(diff пуст)';
    }
    stopPolling();
  }
  if (run.status === 'error') {
    $('status-line').textContent = 'Прогон завершился ошибкой.';
    $('error-panel').classList.remove('hidden');
    $('error').textContent = run.error;
    if (run.diff || run.diff_error) {
      $('diff-panel').classList.remove('hidden');
      $('diff').textContent = run.diff || ('Ошибка получения diff: ' + run.diff_error);
      $('changed-files').replaceChildren();
      for (const file of run.changed_files || []) $('changed-files').appendChild(badge(file));
    }
    stopPolling();
  }
}

function stopPolling() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
  $('run').disabled = false;
}

async function poll() {
  if (!state.runId) return;
  try {
    renderRun(await api('/api/runs/' + state.runId));
  } catch (exc) {
    $('status-line').textContent = 'Ошибка опроса: ' + exc.message;
  }
}

async function startRun() {
  const goal = $('goal').value.trim();
  if (!goal) { $('status-line').textContent = 'Введите цель или выберите сценарий.'; return; }
  $('run').disabled = true;
  state.rendered = 0;
  $('steps').replaceChildren();
  $('steps').classList.add('empty');
  $('steps').textContent = '';
  for (const id of ['answer-panel', 'diff-panel', 'error-panel']) $(id).classList.add('hidden');
  try {
    const { run_id } = await api('/api/runs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal }),
    });
    state.runId = run_id;
    window.lastRunId = run_id;
    state.timer = setInterval(poll, 1000);
    poll();
  } catch (exc) {
    $('status-line').textContent = 'Не удалось запустить: ' + exc.message;
    $('run').disabled = false;
  }
}

async function resetProject() {
  try {
    const result = await api('/api/reset', { method: 'POST' });
    $('status-line').textContent = 'Проект восстановлен из эталона: ' + result.files.length + ' файлов.';
  } catch (exc) {
    $('status-line').textContent = 'Сброс не удался: ' + exc.message;
  }
}

$('run').onclick = startRun;
$('reset').onclick = resetProject;
bootstrap().catch((exc) => { $('status-line').textContent = 'Ошибка запуска UI: ' + exc.message; });
