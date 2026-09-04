let stream = null;
let currentRun = null;
let documentResult = null;

window.setScene = (name, caption) => {
  document.body.dataset.scene = name;
  window.__caption = caption;
};

document.addEventListener('DOMContentLoaded', async () => {
  setupTabs();
  document.getElementById('runButton').addEventListener('click', startRun);
  document.getElementById('stopButton').addEventListener('click', stopRun);
  document.getElementById('replaySelect').addEventListener('change', e => e.target.value && loadReplay(e.target.value));
  const config = await fetch('/api/config').then(r => r.json()).catch(() => ({}));
  const badge = document.getElementById('localBadge');
  badge.textContent = config.local_available ? '⚡ LOCAL 27B: ONLINE' : 'LOCAL: URL не задан';
  badge.className = config.local_available ? 'online' : 'offline';
  const smallBadge = document.getElementById('localSmallBadge');
  smallBadge.textContent = config.local_small_available ? '⚡ OLLAMA 4B: ONLINE' : 'OLLAMA: URL не задан';
  smallBadge.className = config.local_small_available ? 'online' : 'offline';
  const cpuBadge = document.getElementById('localCpuBadge');
  cpuBadge.textContent = config.local_cpu_available ? '⚡ CPU 1.7B: ONLINE' : 'CPU 1.7B: URL не задан';
  cpuBadge.className = config.local_cpu_available ? 'online' : 'offline';
  const apiBadge = document.getElementById('apiBadge');
  const apiOnline = config.gemini_available && config.deepseek_available;
  apiBadge.textContent = apiOnline ? '☁ GEMINI + DEEPSEEK: ONLINE' : 'API: ключи не найдены';
  apiBadge.className = apiOnline ? 'online' : 'offline';
  loadReplays();
});

function setupTabs() {
  document.querySelectorAll('.tab').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('.tab,.tab-panel').forEach(el => el.classList.remove('active'));
    button.classList.add('active');
    document.getElementById(`tab-${button.dataset.tab}`).classList.add('active');
  }));
}

function resetCards() {
  document.querySelectorAll('.model-card').forEach(card => {
    card.classList.remove('running', 'done', 'failed');
    card.querySelector('.progress').textContent = 'ожидает';
    card.querySelector('.answer').textContent = '';
    card.querySelector('.mini').textContent = '';
  });
  document.getElementById('scoreBody').innerHTML = '';
  document.getElementById('verdict').textContent = 'Эксперимент выполняется…';
  document.getElementById('rawOutput').textContent = '';
}

async function startRun() {
  resetCards();
  setStatus('RUNNING');
  document.getElementById('runButton').disabled = true;
  document.getElementById('stopButton').disabled = false;
  window.setScene('running', 'Один prompt · девять моделей · одинаковые параметры');
  const response = await fetch('/api/run', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({repeats: 3, include_local: true, include_local_small: true, include_local_cpu: true, include_api: true})
  });
  const data = await response.json();
  currentRun = data.run_id;
  connect(currentRun);
}

function connect(runId) {
  stream = new EventSource(`/api/runs/${runId}/events`);
  stream.onmessage = event => handleEvent(JSON.parse(event.data));
  stream.onerror = () => {
    stream.close();
    if (document.getElementById('statusLabel').textContent === 'RUNNING') setStatus('FAILED');
  };
}

function cardFor(id) { return document.querySelector(`.model-card[data-model="${id}"]`); }

function handleEvent(event) {
  const data = event.data;
  if (event.type === 'model_started') {
    const card = cardFor(data.id);
    if (card) { card.classList.add('running'); card.querySelector('.progress').textContent = 'запуск…'; }
  } else if (event.type === 'sample_started') {
    const card = cardFor(data.model_id);
    if (card) card.querySelector('.progress').textContent = `прогон ${data.repeat}/3`;
  } else if (event.type === 'token_delta' && data.repeat === 1) {
    const card = cardFor(data.model_id);
    if (card) card.querySelector('.answer').textContent += data.text;
  } else if (event.type === 'sample_finished') {
    updateSample(data);
  } else if (event.type === 'ExperimentFinished') {
    stream.close();
    documentResult = data.document;
    renderResult(documentResult);
    setStatus('DONE');
    document.getElementById('runButton').disabled = false;
    document.getElementById('stopButton').disabled = true;
    window.setScene('verdict', documentResult.verdict);
    loadReplays();
  } else if (event.type === 'ExperimentFailed') {
    stream.close(); setStatus('FAILED');
    document.getElementById('verdict').textContent = data.error;
    document.getElementById('runButton').disabled = false;
    document.getElementById('stopButton').disabled = true;
  } else if (event.type === 'StreamClosed') {
    stream?.close();
  }
}

function updateSample(data) {
  const card = cardFor(data.model_id);
  if (!card) return;
  card.classList.add('done');
  const e = data.evaluation;
  card.querySelector('.progress').textContent = `прогон ${data.repeat}/3 готов`;
  const cost = data.backend === 'local' ? '$0 local' : (data.cost_usd == null ? 'цена н/д' : `$${data.cost_usd.toFixed(6)}`);
  card.querySelector('.mini').textContent = `${e.passed}/${e.total} тестов · ${(data.latency_ms/1000).toFixed(1)}с · ${data.output_tokens ?? '?'} tok · ${cost}`;
}

function renderResult(doc) {
  document.getElementById('promptText').textContent = doc.locked.prompt;
  document.getElementById('rawOutput').textContent = JSON.stringify(doc, null, 2);
  document.getElementById('verdict').textContent = doc.verdict;
  const body = document.getElementById('scoreBody'); body.innerHTML = '';
  doc.models.forEach(model => {
    const m = doc.metrics[model.id]; if (!m) return;
    const row = document.createElement('tr');
    const resource = m.ram_mb_peak
      ? `CPU ${m.cpu_percent_peak.toFixed(0)}% · RAM ${Math.round(m.ram_mb_peak)} MB`
      : (m.vram_mb_peak ? `VRAM ${Math.round(m.vram_mb_peak)} MB` : 'cloud');
    row.innerHTML = `<td><strong>${escapeHtml(m.label)}</strong><small>${m.parameters_b == null ? 'API' : m.parameters_b + 'B'}</small></td>
      <td><span class="score">${m.tests_passed_mean.toFixed(1)}/${m.tests_total}</span></td>
      <td>${(m.latency_ms_median/1000).toFixed(2)} с</td><td>${m.ttft_ms_median == null ? '—' : m.ttft_ms_median + ' мс'}</td>
      <td>${m.tokens_per_second_median?.toFixed(1) ?? '—'}</td><td>${m.output_tokens_median ?? '—'}</td>
      <td>${model.id.startsWith('local') ? '$0' : '$' + m.cost_usd_total.toFixed(6)}</td>
      <td>${resource}</td>`;
    body.appendChild(row);
    const card = cardFor(model.id);
    if (card) card.querySelector('.progress').textContent = `${m.tests_passed_mean.toFixed(1)}/${m.tests_total} · median ${(m.latency_ms_median/1000).toFixed(1)}с`;
  });
}

function escapeHtml(value) {
  const div = document.createElement('div'); div.textContent = value; return div.innerHTML;
}

function setStatus(value) {
  const label = document.getElementById('statusLabel'); label.textContent = value; label.className = `status ${value}`;
}

async function stopRun() {
  if (!currentRun) return;
  await fetch(`/api/runs/${currentRun}/cancel`, {method: 'POST'});
  document.getElementById('stopButton').disabled = true;
}

async function loadReplays() {
  const items = await fetch('/api/results').then(r => r.json()).catch(() => []);
  const select = document.getElementById('replaySelect');
  [...select.options].slice(1).forEach(option => option.remove());
  items.forEach(item => { const option = document.createElement('option'); option.value = item.id; option.textContent = item.name; select.appendChild(option); });
}

async function loadReplay(id) {
  resetCards();
  const doc = await fetch(`/api/result?id=${encodeURIComponent(id)}`).then(r => r.json());
  documentResult = doc; renderResult(doc); setStatus('DONE'); window.setScene('replay', 'Replay реального прогона');
}
