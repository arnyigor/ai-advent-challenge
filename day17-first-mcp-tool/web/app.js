const $ = id => document.getElementById(id);
const steps = ['connect', 'list', 'call', 'answer'];
let busy = false;
function reset() {
  for (const step of steps) $(`step-${step}`).className = 'step';
  for (const id of ['tool-name','schema','call','result']) $(id).textContent = '—';
  $('description').textContent = 'Ожидаем каталог.';
  $('parameters').textContent = 'Ожидаем каталог.';
  $('answer').textContent = 'Запрашиваем данные…';
}
function show(data) {
  $('tool-name').textContent = data.tool;
  $('description').textContent = data.description;
  $('schema').textContent = JSON.stringify(data.inputSchema, null, 2);
  const properties = data.inputSchema.properties || {};
  const required = new Set(data.inputSchema.required || []);
  $('parameters').replaceChildren(...Object.entries(properties).map(([name, value]) => {
    const row = document.createElement('div');
    row.className = 'parameter';
    const label = document.createElement('code'); label.textContent = name;
    const type = document.createElement('span'); type.textContent = value.enum ? value.enum.join(' / ') : value.type || 'object';
    const need = document.createElement('span'); need.textContent = required.has(name) ? 'обязательный' : 'необязательный';
    row.append(label, type, need); return row;
  }));
  $('call').textContent = `${data.server}.${data.tool}(${JSON.stringify(data.arguments)})`;
  $('result').textContent = JSON.stringify(data.result, null, 2);
  $('answer').textContent = data.answer;
  for (const step of steps) $(`step-${step}`).className = 'step done';
  $('status').textContent = 'MCP-вызов выполнен'; $('status').className = 'badge ok';
  $('status-note').textContent = 'Агент использовал результат инструмента в ответе.';
}
$('ask').addEventListener('click', async () => {
  if (busy) return;
  busy = true; reset(); $('ask').disabled = true; $('scope').disabled = true;
  $('status').textContent = 'Вызываем MCP…'; $('status').className = 'badge busy';
  $('status-note').textContent = 'Подключаемся, получаем схему и вызываем инструмент.';
  $('step-connect').className = 'step current';
  try {
    const response = await fetch('/api/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({scope:$('scope').value})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Вызов не удался');
    show(data);
  } catch (error) {
    $('status').textContent = 'Ошибка вызова'; $('status').className = 'badge error';
    $('status-note').textContent = error.message; $('answer').textContent = 'Ответ не получен.';
    $('step-connect').className = 'step';
  } finally { busy = false; $('ask').disabled = false; $('scope').disabled = false; }
});
