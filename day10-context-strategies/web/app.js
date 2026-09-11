const $ = (id) => document.getElementById(id);
const sessionId = localStorage.getItem('day10Session') || crypto.randomUUID();
localStorage.setItem('day10Session', sessionId);
const state = { busy: false, config: null, providers: [], activeBranch: 'main' };

const STRATEGY_HINTS = {
  sliding: 'Только последние N сообщений, остальное отбрасывается.',
  facts: 'Блок «ключ: значение» + последние N сообщений. Память обновляется после каждой реплики пользователя (отдельный вызов модели).',
  branching: 'Вся история активной ветки. Checkpoint → две ветки от одной точки, переключение без потери каждой.',
};

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

function fmt(value) {
  return Number.isFinite(Number(value)) ? Number(value).toLocaleString('ru-RU') : '—';
}

function setBusy(value) {
  state.busy = value;
  $('sendButton').disabled = value;
  $('prompt').disabled = value;
  $('statusText').textContent = value ? 'модель отвечает…' : 'готово';
}

function addMessage(role, content, meta = '') {
  $('emptyState')?.remove();
  const node = document.createElement('div');
  node.className = `msg ${role === 'user' ? 'user' : 'assistant'}`;
  node.innerHTML = `<div class="bubble">${esc(content).replace(/\n/g, '<br>')}</div>${meta ? `<div class="msg-meta">${esc(meta)}</div>` : ''}`;
  $('msgsInner').appendChild(node);
  $('msgs').scrollTop = $('msgs').scrollHeight;
}

function renderMessages(messages) {
  $('msgsInner').innerHTML = '';
  if (!messages.length) {
    $('msgsInner').innerHTML = '<div class="empty" id="emptyState">Ветка пуста. Начните диалог — полная история сохранится, а в модель уйдёт то, что выберет стратегия.</div>';
    return;
  }
  messages.forEach((item) => addMessage(item.role, item.content));
}

function renderUsage(usage = {}) {
  $('sessInput').textContent = fmt(usage.input_tokens || 0);
  $('sessOutput').textContent = fmt(usage.output_tokens || 0);
  $('sessTotal').textContent = fmt(usage.total_tokens || 0);
  $('sessCalls').textContent = fmt((usage.known_calls || 0) + (usage.unknown_calls || 0));
}

function renderFacts(facts = {}) {
  const values = facts.values || facts || {};
  const keys = Object.keys(values);
  $('factsCount').textContent = fmt(keys.length);
  $('factsBox').innerHTML = keys.length
    ? keys.map((key) => `<div class="fact"><b>${esc(key)}</b><span>${esc(values[key])}</span></div>`).join('')
    : 'Пусто. Стратегия Sticky Facts обновляет этот блок после каждого сообщения пользователя.';
}

function renderContext(data = {}) {
  const full = data.full_history_tokens?.value;
  const effective = data.effective_history_tokens?.value;
  $('fullTokens').textContent = full == null ? '—' : `≈${fmt(full)}`;
  $('effectiveTokens').textContent = effective == null ? '—' : `≈${fmt(effective)}`;
  $('savedTokens').textContent = `≈${fmt(data.estimated_tokens_saved_this_request || 0)}`;
  $('droppedCount').textContent = fmt(data.dropped_message_count || 0);
  $('verbatimCount').textContent = fmt(data.verbatim_message_count || 0);
  renderFacts({ values: data.facts || {} });
}

function renderBranching(data = {}) {
  if (!data.branches) return;
  state.activeBranch = data.active || 'main';
  $('checkpointHint').textContent = `Checkpoint: ${fmt(data.checkpoint || 0)} сообщений в ветке «${esc(state.activeBranch)}»`;
  $('branchList').innerHTML = data.branches.map((branch) => {
    const active = branch.branch_id === state.activeBranch;
    const origin = branch.parent_branch_id ? ` ← ${esc(branch.parent_branch_id)}@${branch.fork_index}` : '';
    return `<button type="button" class="branch${active ? ' active' : ''}" data-branch="${esc(branch.branch_id)}">
      <b>${esc(branch.branch_id)}</b><small>${fmt(branch.message_count)} сообщ.${origin}</small></button>`;
  }).join('');
}

function settings() {
  return {
    strategy: $('strategySelect').value,
    recent_messages: Number($('recentMessages').value),
    provider: $('providerSelect').value,
    model: $('modelSelect').value,
    temperature: Number($('temperature').value),
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

function post(path, payload) {
  return api(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, ...payload }),
  });
}

function updateModels() {
  const provider = state.providers.find((item) => item.id === $('providerSelect').value);
  $('modelSelect').innerHTML = '<option value="">По умолчанию</option>';
  (provider?.models || []).forEach((model) => {
    const option = document.createElement('option');
    option.value = model;
    option.textContent = model;
    $('modelSelect').appendChild(option);
  });
  $('modelSelect').disabled = !provider;
}

function applyStrategyUi() {
  const value = $('strategySelect').value;
  const option = $('strategySelect').selectedOptions[0];
  $('strategyBadge').textContent = option ? option.textContent : value;
  $('strategyHint').textContent = STRATEGY_HINTS[value] || '';
  // Окно последних N осмысленно только там, где история режется.
  $('recentMessages').disabled = value === 'branching';
}

async function loadConfig() {
  const data = await api('/api/config');
  state.config = data.config;
  state.providers = data.providers;
  data.providers.forEach((provider) => {
    const option = document.createElement('option');
    option.value = provider.id;
    option.textContent = `${provider.label}${provider.available ? '' : ' (нет ключа)'}`;
    $('providerSelect').appendChild(option);
  });
  (data.config.strategies || []).forEach((item) => {
    const option = document.createElement('option');
    option.value = item.id;
    option.textContent = item.label;
    $('strategySelect').appendChild(option);
  });
  $('strategySelect').value = data.config.strategy;
  $('recentMessages').value = data.config.recent_messages;
  $('temperature').value = data.config.temperature;
  $('temperatureValue').textContent = data.config.temperature;
  applyStrategyUi();
}

async function loadHistory() {
  const data = await api(`/api/history?session_id=${encodeURIComponent(sessionId)}`);
  renderMessages(data.messages || []);
  renderUsage(data.session_usage);
  renderFacts(data.facts);
  renderBranching(data.branching);
}

async function loadComparison() {
  try {
    const data = await api('/api/strategies');
    const rows = (data.strategies || []).map((item) => `<tr>
      <td>${esc(item.label)}</td><td>${esc(item.quality_score)}%</td><td>${fmt(item.total_input_tokens)}</td></tr>`).join('');
    $('comparison').innerHTML = `<table class="mini-table"><thead><tr><th>Стратегия</th><th>Качество</th><th>Вход</th></tr></thead><tbody>${rows}</tbody></table>`;
  } catch (_) {
    // Необязательно, пока run_strategies.py не сделал реальный прогон.
  }
}

$('form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const message = $('prompt').value.trim();
  if (!message || state.busy) return;
  addMessage('user', message);
  $('prompt').value = '';
  setBusy(true);
  try {
    const data = await post('/api/chat', { message, ...settings() });
    const reply = data.reply;
    addMessage('assistant', reply.text, `${reply.provider} · ${reply.model} · ${fmt(reply.usage.total_tokens)} токенов`);
    renderUsage(reply.session_usage);
    renderContext(reply.context);
    renderBranching(data.branching);
  } catch (error) {
    addMessage('assistant', `Ошибка: ${error.message}`);
  } finally {
    setBusy(false);
    $('prompt').focus();
  }
});

$('prompt').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    $('form').requestSubmit();
  }
});

$('forkBtn').addEventListener('click', async () => {
  const branchId = $('branchName').value.trim();
  if (!branchId) return;
  try {
    const data = await post('/api/branch', { action: 'create', branch_id: branchId });
    $('branchName').value = '';
    renderMessages(data.messages || []);
    renderFacts(data.facts);
    renderBranching(data.branching);
  } catch (error) {
    $('statusText').textContent = `ошибка: ${error.message}`;
  }
});

$('branchList').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-branch]');
  if (!button || state.busy) return;
  const data = await post('/api/branch', { action: 'switch', branch_id: button.dataset.branch });
  renderMessages(data.messages || []);
  renderFacts(data.facts);
  renderBranching(data.branching);
});

$('clearContextBtn').addEventListener('click', async () => {
  const data = await post('/api/reset', {});
  renderMessages([]);
  renderUsage({});
  renderContext({});
  renderBranching(data.branching);
});

$('providerSelect').addEventListener('change', updateModels);
$('strategySelect').addEventListener('change', applyStrategyUi);
$('temperature').addEventListener('input', () => { $('temperatureValue').textContent = $('temperature').value; });

Promise.all([loadConfig(), loadHistory(), loadComparison()]).catch((error) => {
  $('statusText').textContent = `ошибка: ${error.message}`;
});
