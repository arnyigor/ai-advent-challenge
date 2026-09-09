const msgsBox = document.getElementById('msgs');
const msgsInner = document.getElementById('msgsInner');
const emptyState = document.getElementById('emptyState');
const form = document.getElementById('form');
const promptInput = document.getElementById('prompt');
const sendButton = document.getElementById('sendButton');
const stopButton = document.getElementById('stopButton');
const clearContextBtn = document.getElementById('clearContextBtn');
const activeProviderLabel = document.getElementById('activeProvider');
const savedIndicator = document.getElementById('savedIndicator');

const providerSelect = document.getElementById('providerSelect');
const modelSelect = document.getElementById('modelSelect');
const modelNote = document.getElementById('modelNote');
const temperatureInput = document.getElementById('temperature');
const temperatureValue = document.getElementById('temperatureValue');
const topPInput = document.getElementById('topP');
const topPValue = document.getElementById('topPValue');
const topKInput = document.getElementById('topK');
const topKValue = document.getElementById('topKValue');
const thinkingSelect = document.getElementById('thinkingSelect');
const contextCharsInput = document.getElementById('contextChars');
const maxHistoryInput = document.getElementById('maxHistory');
const maxOutputTokensInput = document.getElementById('maxOutputTokens');
const forceOverflowApiInput = document.getElementById('forceOverflowApi');
const systemPromptInput = document.getElementById('systemPrompt');
const resetSystemPromptBtn = document.getElementById('resetSystemPromptBtn');

const sessMessages = document.getElementById('sessMessages');
const sessInput = document.getElementById('sessInput');
const sessOutput = document.getElementById('sessOutput');
const sessTotal = document.getElementById('sessTotal');
const sessCompleteness = document.getElementById('sessCompleteness');
const metricCurrent = document.getElementById('metricCurrent');
const metricHistoryBefore = document.getElementById('metricHistoryBefore');
const metricRequest = document.getElementById('metricRequest');
const metricOutput = document.getElementById('metricOutput');
const metricHistoryAfter = document.getElementById('metricHistoryAfter');
const metricContext = document.getElementById('metricContext');
const usageRows = document.getElementById('usageRows');
const usageChart = document.getElementById('usageChart');

const SESSION_KEY = 'day08_session_id';
const sessionId = localStorage.getItem(SESSION_KEY)
  || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
localStorage.setItem(SESSION_KEY, sessionId);

let activeController = null;
let lastMessage = null;
let providersById = {};
let defaultSystemPrompt = '';
let savedTimer = null;
let requestLog = [];

document.addEventListener('DOMContentLoaded', () => {
  loadConfig();
  loadHistory();
});
form.addEventListener('submit', (event) => {
  event.preventDefault();
  const message = promptInput.value.trim();
  if (!message || sendButton.disabled) return;
  promptInput.value = '';
  submitMessage(message);
});
stopButton.addEventListener('click', cancelActiveRequest);
clearContextBtn.addEventListener('click', resetConversation);
resetSystemPromptBtn.addEventListener('click', () => {
  systemPromptInput.value = defaultSystemPrompt;
  flashSaved();
});
promptInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});
providerSelect.addEventListener('change', () => {
  populateModelSelect(providerSelect.value);
  flashSaved();
});

[
  [temperatureInput, temperatureValue, (v) => Number(v).toFixed(1)],
  [topPInput, topPValue, (v) => Number(v).toFixed(2)],
  [topKInput, topKValue, (v) => String(v)],
].forEach(([input, output, format]) => {
  input.addEventListener('input', () => { output.textContent = format(input.value); });
  input.addEventListener('change', flashSaved);
});
[thinkingSelect, contextCharsInput, maxHistoryInput, maxOutputTokensInput, forceOverflowApiInput, systemPromptInput].forEach((el) => {
  el.addEventListener('change', flashSaved);
});

async function loadConfig() {
  try {
    const response = await fetch('/api/config');
    const data = await response.json();
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const providers = Array.isArray(data.providers) ? data.providers : [];
    providersById = Object.fromEntries(providers.map((p) => [p.id, p]));
    populateProviderSelect(providers);
    applyConfigDefaults(data.config || {});
    const primary = providers.find((item) => item.available);
    activeProviderLabel.textContent = primary ? primary.label : 'нет доступных';
  } catch {
    activeProviderLabel.textContent = 'сервер недоступен';
    modelNote.textContent = 'Настройки недоступны';
  }
}

function populateProviderSelect(providers) {
  const options = providers.filter((p) => p.available).map((p) => new Option(p.label, p.id));
  providerSelect.replaceChildren(new Option('Авто (fallback-цепочка)', ''), ...options);
  populateModelSelect('');
}

function populateModelSelect(providerId) {
  const provider = providersById[providerId];
  if (!provider) {
    modelSelect.replaceChildren(new Option('По умолчанию провайдера', ''));
    modelSelect.disabled = true;
    modelNote.textContent = 'Выберите провайдер, чтобы задать конкретную модель.';
    return;
  }
  const models = Array.isArray(provider.models) && provider.models.length ? provider.models : [provider.model];
  modelSelect.replaceChildren(new Option(`По умолчанию (${provider.model})`, ''), ...models.map((m) => new Option(m, m)));
  modelSelect.disabled = models.length <= 1;
  modelNote.textContent = models.length > 1
    ? `Доступно моделей: ${models.length}`
    : `У ${provider.label} только одна модель.`;
}

function applyConfigDefaults(config) {
  defaultSystemPrompt = String(config.system_prompt ?? '');
  systemPromptInput.value = defaultSystemPrompt;
  temperatureInput.value = config.temperature ?? 0.7;
  temperatureValue.textContent = Number(temperatureInput.value).toFixed(1);
  topPInput.value = config.top_p ?? 0.95;
  topPValue.textContent = Number(topPInput.value).toFixed(2);
  topKInput.value = config.top_k ?? 40;
  topKValue.textContent = String(topKInput.value);
  contextCharsInput.value = config.context_chars ?? 24000;
  maxHistoryInput.value = config.max_history_messages ?? 50;
  maxOutputTokensInput.value = config.max_output_tokens ?? 1024;

  const levels = Array.isArray(config.thinking_levels) ? config.thinking_levels : [];
  thinkingSelect.replaceChildren(...levels.map((level) => new Option(level, level)));
  if (config.thinking_level) thinkingSelect.value = config.thinking_level;
}

function flashSaved(isError = false) {
  clearTimeout(savedTimer);
  savedIndicator.textContent = isError ? 'не сохранено' : 'сохранено';
  savedIndicator.classList.toggle('err', isError);
  savedIndicator.classList.add('on');
  savedTimer = setTimeout(() => savedIndicator.classList.remove('on'), 1600);
}

function currentSettings() {
  return {
    provider: providerSelect.value || null,
    model: modelSelect.value || null,
    thinking_level: thinkingSelect.value || null,
    temperature: Number(temperatureInput.value),
    top_p: Number(topPInput.value),
    top_k: Number(topKInput.value),
    context_chars: Number(contextCharsInput.value),
    max_history_messages: Number(maxHistoryInput.value),
    max_output_tokens: Number(maxOutputTokensInput.value),
    force_overflow_api: Boolean(forceOverflowApiInput.checked),
    system_prompt: systemPromptInput.value.trim() || null,
  };
}

async function submitMessage(message) {
  lastMessage = message;
  const userTurn = appendUserMessage(message);
  setBusy(true);
  const pending = appendPending();
  activeController = new AbortController();
  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, message, ...currentSettings() }),
      signal: activeController.signal,
    });
    const data = await response.json();
    pending.remove();
    if (!response.ok) {
      if (data.cancelled) {
        appendErrorMessage('Запрос отменён', userTurn);
        return;
      }
      const error = new Error(data.error || `HTTP ${response.status}`);
      error.tokenMetrics = data.token_metrics || null;
      if (data.context_limit) error.contextLimit = true;
      throw error;
    }
    const reply = data.reply;
    appendBotMessage(reply);
    updateSessionStats(reply.session_usage);
    updateMetrics(reply.token_metrics, reply.usage);
    requestLog.push({
      turn_index: reply.turn_index,
      provider: reply.provider,
      model: reply.model,
      status: reply.status,
      metrics: reply.token_metrics,
      usage: reply.usage,
    });
    renderUsageLog();
    activeProviderLabel.textContent = providersById[reply.provider]?.label || reply.provider;
  } catch (error) {
    pending.remove();
    if (error.name === 'AbortError') {
      appendErrorMessage('Запрос отменён', userTurn);
      return;
    }
    appendErrorMessage(error.message || 'Не удалось получить ответ', userTurn, error.tokenMetrics);
  } finally {
    activeController = null;
    setBusy(false);
    promptInput.focus();
  }
}

async function loadHistory() {
  try {
    const response = await fetch(`/api/history?session_id=${encodeURIComponent(sessionId)}`);
    if (!response.ok) return;
    const data = await response.json();
    const messages = Array.isArray(data.messages) ? data.messages : [];
    messages.forEach((m) => {
      if (m.role === 'user') appendUserMessage(m.content);
      else appendRestoredBotMessage(m.content);
    });
    requestLog = Array.isArray(data.request_log) ? data.request_log : [];
    renderUsageLog();
    updateSessionStats(data.session_usage);
    const last = [...requestLog].reverse().find((row) => row.metrics);
    if (last) updateMetrics(last.metrics, last.usage);
  } catch {
    // Restoring history is best effort; an empty chat is a safe fallback.
  }
}

function appendRestoredBotMessage(text) {
  hideEmptyState();
  const turn = createElement('div', 'turn');
  turn.append(botAvatar());
  const body = createElement('div', 'body');
  const bubble = createElement('div', 'msg s-bot');
  const md = createElement('div', 'md');
  md.innerHTML = renderMarkdown(String(text));
  bubble.append(md);
  body.append(bubble);
  turn.append(body);
  msgsInner.appendChild(turn);
  scrollToBottom();
  incrementMessageCount();
}

function hideEmptyState() {
  if (emptyState.isConnected) emptyState.remove();
}

function appendUserMessage(text) {
  hideEmptyState();
  const turn = createElement('div', 'turn me');
  const body = createElement('div', 'body');
  const bubble = createElement('div', 'msg s-me');
  bubble.textContent = text;
  body.append(bubble);
  turn.append(body);
  msgsInner.appendChild(turn);
  scrollToBottom();
  incrementMessageCount();
  return turn;
}

function appendBotMessage(reply) {
  hideEmptyState();
  const turn = createElement('div', 'turn');
  turn.append(botAvatar());
  const body = createElement('div', 'body');

  if (reply.reasoning) {
    body.append(reasoningSpoiler(reply.reasoning));
  }

  const bubble = createElement('div', 'msg s-bot');
  const md = createElement('div', 'md');
  md.innerHTML = renderMarkdown(String(reply.text));
  bubble.append(md);
  body.append(bubble, createElement('div', 'meta', formatReplyMeta(reply)));
  turn.append(body);
  msgsInner.appendChild(turn);
  scrollToBottom();
  incrementMessageCount();
  return turn;
}

function reasoningSpoiler(text) {
  const details = document.createElement('details');
  details.className = 'reasoning';
  const summary = document.createElement('summary');
  summary.textContent = `Рассуждение · ${text.length} симв.`;
  const body = createElement('pre', 'r-text', text);
  details.append(summary, body);
  return details;
}

function botAvatar() {
  const av = createElement('div', 'av');
  av.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2 L14 9 L21 12 L14 15 L12 22 L10 15 L3 12 L10 9 Z"/></svg>';
  return av;
}

function appendErrorMessage(text, userTurn, metrics = null) {
  hideEmptyState();
  const turn = createElement('div', 'turn');
  turn.append(botAvatar());
  const body = createElement('div', 'body');
  const bubble = createElement('div', 'msg err', text);
  if (metrics) {
    const meta = createElement('div', 'error-metrics', formatMetricsLine(metrics));
    bubble.append(meta);
    updateMetrics(metrics, null);
  }
  if (lastMessage) {
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'retry-button';
    retry.textContent = 'Повторить';
    retry.addEventListener('click', () => {
      // The failed/cancelled attempt already added a user bubble — drop it
      // so the retry's fresh submitMessage() doesn't leave a duplicate.
      if (userTurn) {
        userTurn.remove();
        decrementMessageCount();
      }
      turn.remove();
      submitMessage(lastMessage);
    });
    bubble.append(retry);
  }
  body.append(bubble);
  turn.append(body);
  msgsInner.appendChild(turn);
  scrollToBottom();
  return turn;
}

function appendPending() {
  const turn = createElement('div', 'turn');
  turn.append(botAvatar());
  const body = createElement('div', 'body');
  const bubble = createElement('div', 'msg s-bot');
  const typing = createElement('div', 'typing');
  typing.append(document.createElement('i'), document.createElement('i'), document.createElement('i'));
  bubble.append(typing);
  body.append(bubble);
  turn.append(body);
  msgsInner.appendChild(turn);
  scrollToBottom();
  return turn;
}

async function resetConversation() {
  if (clearContextBtn.disabled) return;
  setBusy(true);
  try {
    const response = await fetch('/api/reset', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    msgsInner.querySelectorAll('.turn').forEach((item) => item.remove());
    msgsInner.appendChild(emptyState);
    sessMessages.textContent = '0';
    sessInput.textContent = '0';
    sessOutput.textContent = '0';
    sessTotal.textContent = '0';
    sessCompleteness.textContent = '—';
    requestLog = [];
    renderUsageLog();
    updateMetrics(null, null);
    flashSaved();
  } catch (error) {
    appendErrorMessage(error.message || 'Не удалось очистить контекст');
  } finally {
    setBusy(false);
    promptInput.focus();
  }
}

async function cancelActiveRequest() {
  if (!activeController) return;
  stopButton.disabled = true;
  try {
    await fetch('/api/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    });
  } catch {
    // Local cancellation is best effort; aborting the browser request still stops the UI.
  } finally {
    activeController.abort();
  }
}

function setBusy(value) {
  sendButton.disabled = value;
  clearContextBtn.disabled = value;
  promptInput.disabled = value;
  providerSelect.disabled = value;
  modelSelect.disabled = value || modelSelect.options.length <= 1;
  forceOverflowApiInput.disabled = value;
  stopButton.disabled = !value;
  document.querySelectorAll('.retry-button').forEach((button) => { button.disabled = value; });
}

function formatReplyMeta(reply) {
  const attempts = Array.isArray(reply.attempts) ? reply.attempts.length : 0;
  const current = formatUsage(reply.usage);
  const requestTokens = formatCount(reply.token_metrics?.request_tokens_before_send);
  return `${reply.provider} · ${reply.model} · ход ${reply.turn_index} · попыток: ${attempts} · вход до отправки ${requestTokens} · API usage: ${current || 'н/д'}`;
}

function formatUsage(usage) {
  if (!usage || usage.reported !== true) return null;
  return `вход ${usage.input_tokens} · выход ${usage.output_tokens} · всего ${usage.total_tokens}`;
}

function updateSessionStats(usage) {
  if (!usage) return;
  sessInput.textContent = String(usage.input_tokens ?? 0);
  sessOutput.textContent = String(usage.output_tokens ?? 0);
  sessTotal.textContent = String(usage.total_tokens ?? 0);
  if (usage.reported === true && usage.complete !== false) {
    sessCompleteness.textContent = 'полная';
  } else if (usage.reported === true) {
    sessCompleteness.textContent = `неполная (${usage.unknown_calls ?? 0} н/д)`;
  } else {
    sessCompleteness.textContent = 'н/д';
  }
}

function updateMetrics(metrics, usage) {
  metricCurrent.textContent = metrics ? formatCount(metrics.current_message_tokens) : '—';
  metricHistoryBefore.textContent = metrics ? formatCount(metrics.history_tokens_before) : '—';
  metricRequest.textContent = metrics ? formatCount(metrics.request_tokens_before_send) : '—';
  metricOutput.textContent = usage?.reported === true
    ? String(usage.output_tokens)
    : (metrics ? formatCount(metrics.visible_answer_tokens) : '—');
  metricHistoryAfter.textContent = metrics ? formatCount(metrics.history_tokens_after) : '—';
  const budget = metrics?.context_budget;
  if (!budget) {
    metricContext.textContent = '—';
    metricContext.classList.remove('bad');
  } else {
    const request = budget.request_tokens ?? 'н/д';
    const limit = budget.context_window_tokens ?? 'н/д';
    const overflow = budget.overflow_tokens > 0 ? ` +${budget.overflow_tokens}` : '';
    metricContext.textContent = `${request}/${limit}${overflow}`;
    metricContext.classList.toggle('bad', budget.status === 'local_context_limit');
  }
}

function formatCount(item) {
  if (!item || item.value === undefined || item.value === null) return 'н/д';
  return `${item.is_estimate ? '≈' : ''}${item.value}`;
}

function formatMetricsLine(metrics) {
  const budget = metrics?.context_budget || {};
  return `Вход ${formatCount(metrics?.request_tokens_before_send)}, лимит ${budget.context_window_tokens || 'н/д'}, резерв ответа ${budget.response_reserve_tokens || 'н/д'}`;
}

function renderUsageLog() {
  let cumulative = 0;
  const rows = requestLog.map((row) => {
    const usage = row.usage || {};
    if (usage.reported === true) cumulative += Number(usage.total_tokens || 0);
    const tr = document.createElement('tr');
    const input = usage.reported === true
      ? usage.input_tokens
      : formatCount(row.metrics?.request_tokens_before_send);
    const output = usage.reported === true ? usage.output_tokens : 'н/д';
    const total = usage.reported === true ? usage.total_tokens : row.status;
    [row.turn_index, input, output, total, cumulative || 'н/д'].forEach((value) => {
      const td = document.createElement('td');
      td.textContent = String(value ?? '—');
      tr.append(td);
    });
    return tr;
  });
  usageRows.replaceChildren(...rows);
  renderChart();
}

function renderChart() {
  const points = requestLog.map((row, index) => ({
    x: index + 1,
    input: Number(row.usage?.reported === true
      ? row.usage.input_tokens
      : row.metrics?.request_tokens_before_send?.value || 0),
  })).filter((point) => point.input > 0);
  if (!points.length) {
    usageChart.textContent = 'Нет данных';
    return;
  }
  const width = 280;
  const height = 120;
  const pad = 18;
  const maxInput = Math.max(...points.map((p) => p.input), 1);
  const maxX = Math.max(...points.map((p) => p.x), 1);
  const coords = points.map((p) => {
    const x = pad + ((p.x - 1) / Math.max(1, maxX - 1)) * (width - pad * 2);
    const y = height - pad - (p.input / maxInput) * (height - pad * 2);
    return {x, y, label: p.input, turn: p.x};
  });
  const polyline = coords.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  usageChart.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Рост входных токенов">
      <path d="M${pad} ${height - pad}H${width - pad}M${pad} ${pad}V${height - pad}" />
      <polyline points="${polyline}" />
      ${coords.map((p) => `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="3"><title>Ход ${p.turn}: ${p.label}</title></circle>`).join('')}
    </svg>
  `;
}

function incrementMessageCount() {
  sessMessages.textContent = String(Number(sessMessages.textContent) + 1);
}

function decrementMessageCount() {
  sessMessages.textContent = String(Math.max(0, Number(sessMessages.textContent) - 1));
}

function scrollToBottom() {
  msgsBox.scrollTop = msgsBox.scrollHeight;
}

function escapeHtml(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderInline(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>');
}

// A trailing run of bullet/numbered lines becomes a list; any lines before it
// (a lead-in sentence with no blank line before the list, common in LLM
// output) stay a paragraph instead of failing list detection entirely.
function extractListTail(lines, itemPattern) {
  let i = lines.length;
  while (i > 0 && itemPattern.test(lines[i - 1].trim())) i--;
  if (i === lines.length) return null;
  return {
    tag: itemPattern.source.startsWith('^\\d') ? 'ol' : 'ul',
    intro: lines.slice(0, i),
    items: lines.slice(i).map((line) => line.trim().replace(itemPattern, '')),
  };
}

// ponytail: regex markdown covers what LLM replies actually use (bold,
// italic, inline code, fenced code, lists, paragraphs) — swap for a real
// parser only if output starts using tables/nested lists/links.
function renderMarkdown(text) {
  const codeBlocks = [];
  const withPlaceholders = text.replace(/```[a-zA-Z0-9_-]*\n([\s\S]*?)```/g, (_match, code) => {
    codeBlocks.push(`<pre><code>${escapeHtml(code.replace(/\n$/, ''))}</code></pre>`);
    return ` ${codeBlocks.length - 1} `;
  });

  return withPlaceholders
    .split(/\n{2,}/)
    .map((block) => {
      const placeholder = block.trim().match(/^ (\d+) $/);
      if (placeholder) return codeBlocks[Number(placeholder[1])];

      let lines = block.split('\n').filter((line) => line.length > 0);
      let heading = '';
      const headingMatch = lines[0] && lines[0].match(/^(#{1,6})\s+(.*)$/);
      if (headingMatch) {
        const level = Math.min(headingMatch[1].length + 2, 6);
        heading = `<h${level}>${renderInline(headingMatch[2])}</h${level}>`;
        lines = lines.slice(1);
      }
      if (!lines.length) return heading;

      const list = extractListTail(lines, /^[-*]\s+/) || extractListTail(lines, /^\d+\.\s+/);
      if (list) {
        const intro = list.intro.length ? `<p>${list.intro.map(renderInline).join('<br>')}</p>` : '';
        const items = list.items.map((line) => `<li>${renderInline(line)}</li>`).join('');
        return `${heading}${intro}<${list.tag}>${items}</${list.tag}>`;
      }
      return `${heading}<p>${lines.map(renderInline).join('<br>')}</p>`;
    })
    .join('');
}

function createElement(tagName, className = '', text = '') {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (text !== '') node.textContent = text;
  return node;
}
