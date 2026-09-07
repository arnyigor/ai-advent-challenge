const chat = document.getElementById('chat');
const form = document.getElementById('form');
const promptInput = document.getElementById('prompt');
const sendButton = document.getElementById('sendButton');
const stopButton = document.getElementById('stopButton');
const resetButton = document.getElementById('resetButton');
const agentState = document.getElementById('agentState');
const sessionUsage = document.getElementById('sessionUsage');
const providerSelect = document.getElementById('providerSelect');
const thinkingSelect = document.getElementById('thinkingSelect');
const sessionId = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
let activeController = null;
let lastMessage = null;

document.addEventListener('DOMContentLoaded', loadConfig);
form.addEventListener('submit', (event) => {
  event.preventDefault();
  const message = promptInput.value.trim();
  if (!message || sendButton.disabled) return;
  promptInput.value = '';
  submitMessage(message);
});
stopButton.addEventListener('click', cancelActiveRequest);
resetButton.addEventListener('click', resetConversation);
promptInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

async function loadConfig() {
  const container = document.getElementById('providers');
  try {
    const response = await fetch('/api/config');
    const config = await response.json();
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const providers = Array.isArray(config.providers) ? config.providers : [];
    container.replaceChildren(...providers.map(providerChip));
    renderAgentConfig(config.config);
    populatePickers(providers, config.config);
    const primary = providers.find(item => item.available);
    document.getElementById('routeProvider').textContent = primary ? `${primary.label} API` : 'LLM API';
  } catch {
    container.replaceChildren(createElement('span', 'provider offline', 'Сервер недоступен'));
    document.getElementById('configChips').replaceChildren(
      createElement('span', 'config-chip offline', 'Настройки недоступны'),
    );
  }
}

function providerChip(provider) {
  const chip = document.createElement('span');
  chip.className = `provider ${provider.available ? 'online' : 'offline'}`;
  chip.append(
    document.createElement('i'),
    createElement('b', '', String(provider.label || provider.id || 'LLM')),
    createElement('small', '', String(provider.model || 'model n/a')),
  );
  return chip;
}

function renderAgentConfig(config) {
  const container = document.getElementById('configChips');
  if (!config || typeof config !== 'object') {
    container.replaceChildren(createElement('span', 'config-chip offline', 'Настройки недоступны'));
    return;
  }
  const chips = [
    ['Температура', config.temperature],
    ['Max tokens', config.max_output_tokens],
    ['Reasoning', config.thinking_level],
    ['История', `${config.max_history_messages} сообщений`],
    ['Input policy', config.input_policy],
    ['Output policy', config.output_policy],
    ['Judge', config.judge_enabled ? 'on' : 'off'],
  ];
  container.replaceChildren(...chips.map(([label, value]) => configChip(label, value)));
}

function populatePickers(providers, config) {
  const providerOptions = providers
    .filter(item => item.available)
    .map(item => new Option(item.label, item.id));
  providerSelect.replaceChildren(new Option('Авто (fallback-цепочка)', ''), ...providerOptions);

  const levels = Array.isArray(config && config.thinking_levels) ? config.thinking_levels : [];
  thinkingSelect.replaceChildren(...levels.map(level => new Option(level, level)));
  if (config && config.thinking_level) thinkingSelect.value = config.thinking_level;
}

function configChip(label, value) {
  const chip = document.createElement('span');
  chip.className = 'config-chip';
  chip.append(
    createElement('small', '', label),
    createElement('b', '', String(value ?? 'н/д')),
  );
  return chip;
}

async function submitMessage(message) {
  lastMessage = message;
  appendMessage('user', message);
  setBusy(true);
  const pending = appendPending();
  activeController = new AbortController();
  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        session_id: sessionId,
        message,
        provider: providerSelect.value || null,
        thinking_level: thinkingSelect.value || null,
      }),
      signal: activeController.signal,
    });
    const data = await response.json();
    pending.remove();
    if (!response.ok) {
      if (data.cancelled) {
        appendErrorMessage('Запрос отменён');
        return;
      }
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    const reply = data.reply;
    appendMessage('assistant', reply.text, formatReplyMeta(reply));
    updateSessionUsage(reply.session_usage);
    document.getElementById('routeProvider').textContent = `${reply.provider} API`;
  } catch (error) {
    pending.remove();
    if (error.name === 'AbortError') {
      appendErrorMessage('Запрос отменён');
      return;
    }
    appendErrorMessage(error.message || 'Не удалось получить ответ');
  } finally {
    activeController = null;
    setBusy(false);
    promptInput.focus();
  }
}

function appendMessage(role, text, meta = '') {
  const article = document.createElement('article');
  article.className = `message ${role}`;
  const avatar = role === 'user' ? 'Вы' : role === 'error' ? '!' : 'A';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  if (role === 'assistant') {
    const body = document.createElement('div');
    body.className = 'msg-text';
    body.innerHTML = renderMarkdown(String(text));
    bubble.append(body);
  } else {
    bubble.append(createElement('p', '', String(text)));
  }
  if (meta) bubble.append(createElement('div', 'meta', meta));
  article.append(createElement('div', 'avatar', avatar), bubble);
  chat.appendChild(article);
  chat.scrollTop = chat.scrollHeight;
  return article;
}

function appendErrorMessage(text) {
  const article = appendMessage('error', text);
  if (!lastMessage) return article;
  const bubble = article.querySelector('.bubble');
  const retry = document.createElement('button');
  retry.type = 'button';
  retry.className = 'retry-button';
  retry.textContent = 'Повторить';
  retry.addEventListener('click', () => {
    article.remove();
    submitMessage(lastMessage);
  });
  bubble.append(retry);
  return article;
}

function appendPending() {
  const article = document.createElement('article');
  article.className = 'message assistant pending';
  const typing = createElement('div', 'typing');
  typing.append(document.createElement('i'), document.createElement('i'), document.createElement('i'));
  const bubble = createElement('div', 'bubble');
  bubble.append(typing, createElement('div', 'meta', 'Агент вызывает LLM API…'));
  article.append(createElement('div', 'avatar', 'A'), bubble);
  chat.appendChild(article);
  chat.scrollTop = chat.scrollHeight;
  return article;
}

async function resetConversation() {
  if (resetButton.disabled) return;
  setBusy(true);
  try {
    const response = await fetch('/api/reset', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({session_id: sessionId}),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    chat.querySelectorAll('.message:not(.welcome)').forEach(item => item.remove());
    sessionUsage.textContent = 'Сессия: 0 токенов';
  } catch (error) {
    appendMessage('error', error.message || 'Не удалось очистить контекст');
  } finally {
    setBusy(false);
    promptInput.focus();
  }
}

async function cancelActiveRequest() {
  if (!activeController) return;
  stopButton.disabled = true;
  agentState.textContent = 'ChatAgent · CANCELLING';
  try {
    await fetch('/api/cancel', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({session_id: sessionId}),
    });
  } catch {
    // Local cancellation is best effort; aborting the browser request still stops the UI.
  } finally {
    activeController.abort();
  }
}

function setBusy(value) {
  sendButton.disabled = value;
  resetButton.disabled = value;
  promptInput.disabled = value;
  providerSelect.disabled = value;
  thinkingSelect.disabled = value;
  stopButton.disabled = !value;
  document.querySelectorAll('.retry-button').forEach((button) => { button.disabled = value; });
  agentState.textContent = value ? 'ChatAgent · THINKING' : 'ChatAgent · READY';
}

function formatReplyMeta(reply) {
  const attempts = Array.isArray(reply.attempts) ? reply.attempts.length : 0;
  const current = formatUsage(reply.usage);
  const cumulative = formatUsage(reply.session_usage);
  const reasoning = reply.usage && reply.usage.reported === true
    ? `reasoning tokens: ${reply.usage.reasoning_tokens || 0}`
    : 'reasoning tokens: н/д';
  const tokenMeta = current
    ? `токены: ${current} · сессия: ${cumulative || 'н/д'}`
    : `токены: н/д · сессия: ${cumulative || 'н/д'}`;
  return `${reply.provider} · ${reply.model} · попыток: ${attempts} · ${reasoning} · ${tokenMeta}`;
}

function formatUsage(usage) {
  if (!usage || usage.reported !== true) return null;
  return `вход ${usage.input_tokens} · выход ${usage.output_tokens} · всего ${usage.total_tokens}`;
}

function updateSessionUsage(usage) {
  if (!usage || usage.reported !== true) {
    sessionUsage.textContent = 'Сессия: токены н/д';
    return;
  }
  sessionUsage.textContent = `Сессия: ${usage.total_tokens} токенов`;
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
    return `\u0000${codeBlocks.length - 1}\u0000`;
  });

  return withPlaceholders
    .split(/\n{2,}/)
    .map((block) => {
      const placeholder = block.trim().match(/^\u0000(\d+)\u0000$/);
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
