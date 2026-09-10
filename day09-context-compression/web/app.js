const $ = (id) => document.getElementById(id);
const sessionId = localStorage.getItem('day09Session') || crypto.randomUUID();
localStorage.setItem('day09Session', sessionId);
const state = { busy: false, config: null, providers: [] };

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
    $('msgsInner').innerHTML = '<div class="empty" id="emptyState">История пуста. Сообщения будут сохранены целиком, даже когда запрос к модели станет короче.</div>';
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

function renderCompression(data = {}) {
  const full = data.full_history_tokens?.value;
  const effective = data.effective_history_tokens?.value;
  $('fullTokens').textContent = full == null ? '—' : `≈${fmt(full)}`;
  $('effectiveTokens').textContent = effective == null ? '—' : `≈${fmt(effective)}`;
  $('savedTokens').textContent = `≈${fmt(data.estimated_tokens_saved_this_request || 0)}`;
  $('summarizedCount').textContent = fmt(data.summarized_message_count || 0);
  $('verbatimCount').textContent = fmt(data.verbatim_message_count || 0);
  $('summaryRevision').textContent = fmt(data.summary_revision || 0);
  $('summaryText').textContent = data.summary_text || 'Сводка ещё не создана. Она появится, когда накопится полный пакет старых сообщений.';
}

function renderSavedSummary(summary = {}) {
  $('summarizedCount').textContent = fmt(summary.summarized_message_count || 0);
  $('summaryRevision').textContent = fmt(summary.revision || 0);
  $('summaryText').textContent = summary.content || 'Сводка ещё не создана. Она появится, когда накопится полный пакет старых сообщений.';
}

function settings() {
  return {
    compression_enabled: $('compressionEnabled').checked,
    recent_messages: Number($('recentMessages').value),
    summary_batch_size: Number($('batchSize').value),
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
  $('compressionEnabled').checked = data.config.compression_enabled;
  $('recentMessages').value = data.config.recent_messages;
  $('batchSize').value = data.config.summary_batch_size;
  $('temperature').value = data.config.temperature;
  $('temperatureValue').textContent = data.config.temperature;
}

async function loadHistory() {
  const data = await api(`/api/history?session_id=${encodeURIComponent(sessionId)}`);
  renderMessages(data.messages || []);
  renderUsage(data.session_usage);
  renderSavedSummary(data.summary);
}

async function loadComparison() {
  try {
    const data = await api('/api/comparison');
    const full = data.modes?.full_history;
    const compressed = data.modes?.compressed;
    if (!full || !compressed) return;
    $('comparison').innerHTML = `<table class="mini-table"><thead><tr><th>Режим</th><th>Качество</th><th>Вход</th></tr></thead><tbody><tr><td>Полная</td><td>${esc(full.quality_score)}</td><td>${fmt(full.total_input_tokens)}</td></tr><tr><td>Summary</td><td>${esc(compressed.quality_score)}</td><td>${fmt(compressed.total_input_tokens)}</td></tr></tbody></table><b class="saving">Экономия входа: ${fmt(data.comparison?.input_token_saving_percent)}%</b>`;
  } catch (_) {
    // Optional until the comparison runner has produced results/comparison.json.
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
    const data = await api('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, message, ...settings() }),
    });
    const reply = data.reply;
    addMessage('assistant', reply.text, `${reply.provider} · ${reply.model} · ${fmt(reply.usage.total_tokens)} токенов`);
    renderUsage(reply.session_usage);
    renderCompression(reply.compression);
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

$('clearContextBtn').addEventListener('click', async () => {
  await api('/api/reset', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  });
  renderMessages([]);
  renderUsage({});
  renderCompression({});
});

$('providerSelect').addEventListener('change', updateModels);
$('temperature').addEventListener('input', () => { $('temperatureValue').textContent = $('temperature').value; });
$('compressionEnabled').addEventListener('change', () => {
  $('modeBadge').textContent = $('compressionEnabled').checked ? 'Сжатие' : 'Полная история';
});

Promise.all([loadConfig(), loadHistory(), loadComparison()]).catch((error) => {
  $('statusText').textContent = `ошибка: ${error.message}`;
});
