const $ = id => document.getElementById(id);
if (new URLSearchParams(location.search).has('demo')) document.body.classList.add('demo');
let history = [], snapshot = null, answer = '', pending = null;
function status(text, error = false) {$('status').textContent = text; $('status').className = error ? 'error' : '';}
function controls() {
  const busy = !!pending;
  ['source', 'mode', 'reset', 'transform'].forEach(id => $(id).disabled = busy);
  $('cancel').hidden = !busy;
  ['copy', 'save'].forEach(id => $(id).disabled = !answer);
  $('refine').disabled = busy || !snapshot;
  $('refine-button').disabled = busy || !snapshot || history.length >= 12;
}
function renderHistory() {
  $('history').replaceChildren();
  history.forEach(item => {const p = document.createElement('p'); p.textContent = `${item.role === 'user' ? 'Запрос' : 'Ответ'}: ${item.content}`; $('history').append(p);});
}
async function run(refine) {
  if (pending) return;
  const input = refine ? {...snapshot, history, message: $('refine').value.trim()} : {text: $('source').value.trim(), mode: $('mode').value, history: []};
  if (!input.text || (refine && !input.message)) return status('Введите текст запроса.', true);
  pending = new AbortController(); controls(); status('Локальная модель обрабатывает текст…');
  try {
    const response = await fetch(refine ? '/api/refine' : '/api/transform', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(input), signal: pending.signal});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || `HTTP ${response.status}`);
    answer = data.answer; $('result').textContent = answer;
    if (refine) history = [...history, {role: 'user', content: input.message}, {role: 'assistant', content: answer}];
    else {snapshot = {text: input.text, mode: input.mode}; history = [{role: 'user', content: 'Выполни выбранную обработку исходного текста.'}, {role: 'assistant', content: answer}];}
    $('refine').value = ''; renderHistory();
    $('meta').textContent = `${data.model} · ${(data.elapsedMs / 1000).toFixed(1)} с · ${data.usage?.total_tokens != null ? `${data.usage.total_tokens} токенов · ` : ''}finish_reason: ${data.finishReason ?? 'не указан'}`;
    status(data.finishReason === 'length' ? 'Ответ обрезан лимитом модели. Можно попросить сократить его.' : 'Готово. Проверьте факты перед использованием.', data.finishReason === 'length');
  } catch (error) {status(error.name === 'AbortError' ? 'Запрос отменён. Предыдущий результат сохранён.' : error.message, true);}
  finally {pending = null; controls();}
}
$('source').addEventListener('input', () => {$('count').textContent = `${$('source').value.length.toLocaleString('ru')} / 12 000`;});
$('transform').addEventListener('click', () => run(false));
$('refine-form').addEventListener('submit', e => {e.preventDefault(); run(true);});
$('cancel').addEventListener('click', () => pending?.abort());
$('reset').addEventListener('click', () => {history = []; snapshot = null; answer = ''; $('source').value = ''; $('count').textContent = '0 / 12 000'; $('refine').value = ''; $('result').textContent = 'Здесь появится ответ локальной модели.'; $('meta').textContent = ''; renderHistory(); status('Готов к работе'); controls();});
$('copy').addEventListener('click', async () => {try {await navigator.clipboard.writeText(answer); status('Результат скопирован.');} catch {status('Не удалось скопировать. Выделите текст результата вручную.', true);}});
$('save').addEventListener('click', () => {const url = URL.createObjectURL(new Blob([answer], {type: 'text/plain;charset=utf-8'})); const a = document.createElement('a'); a.href = url; a.download = 'edited-text.txt'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);});
fetch('/api/config').then(r => {if (!r.ok) throw Error(); return r.json();}).then(data => {$('connection').textContent = `${data.model} · ${data.base}`;}).catch(() => {$('connection').textContent = 'Не удалось прочитать конфигурацию сервера';});
