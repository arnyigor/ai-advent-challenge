const $ = id => document.getElementById(id);
let profiles = [], tools = [], selected = '', busy = false;
const node = (tag, text, className) => { const item = document.createElement(tag); item.textContent = text; if(className) item.className = className; return item; };
function status(text, kind = '') { $('status').textContent = text; $('status').className = `badge ${kind}`; }
function clearResult() {
  tools = []; selected = ''; $('search').value = ''; $('search').disabled = true;
  for (const id of ['server-name','tool-count','protocol','transport']) $(id).textContent = '—';
  for (const id of ['step-connect','step-init','step-list']) $(id).className = 'step';
  $('found').textContent = '0';
  $('tools').replaceChildren(node('p', 'Подключитесь, чтобы получить каталог инструментов.', 'empty'));
  $('detail').replaceChildren(node('p', 'Выберите инструмент после подключения к серверу.', 'empty'));
}
function describeProfile() {
  const profile = profiles.find(item => item.id === $('server').value);
  $('server-description').textContent = profile?.description || '';
}
function renderEvents(events) {
  $('events').replaceChildren(...events.map(event => {
    const li = node('li', '', event.stage === 'error' ? 'error' : '');
    li.append(node('time', event.time), node('span', event.message)); return li;
  }));
}
function renderTools() {
  const query = $('search').value.trim().toLowerCase();
  const visible = tools.filter(tool => `${tool.name} ${tool.description || ''}`.toLowerCase().includes(query));
  $('found').textContent = `${visible.length} / ${tools.length}`;
  if (!visible.length) {
    $('tools').replaceChildren(node('p', tools.length ? 'Ничего не найдено. Попробуйте другое название.' : 'Сервер не предоставил инструментов.', 'empty'));
    selected = '';
    $('detail').replaceChildren(node('p', 'Выберите другой запрос, чтобы увидеть инструмент.', 'empty'));
    return;
  }
  if (!visible.some(tool => tool.name === selected)) {
    selected = visible[0].name;
    renderDetail(visible[0]);
  }
  $('tools').replaceChildren(...visible.map(tool => {
    const button = node('button', '', `tool${tool.name === selected ? ' active' : ''}`);
    button.type = 'button'; button.setAttribute('aria-pressed', String(tool.name === selected));
    button.dataset.tool = tool.name;
    button.append(node('b', tool.name), node('span', tool.description || 'Описание отсутствует'));
    button.addEventListener('click', () => { selected = tool.name; renderTools(); renderDetail(tool); });
    return button;
  }));
}
function schemaType(schema) {
  if (schema.type) return Array.isArray(schema.type) ? schema.type.join(' / ') : schema.type;
  if (schema.anyOf) return schema.anyOf.map(schemaType).join(' / ');
  return schema.$ref ? schema.$ref.split('/').pop() : 'объект';
}
function renderDetail(tool) {
  const schema = tool.inputSchema || {}, required = new Set(schema.required || []);
  const detail = $('detail'); detail.replaceChildren(node('span', 'ИНСТРУМЕНТ MCP', 'eyebrow'), node('h2', tool.name));
  detail.append(node('p', tool.description || 'Сервер не передал описание.', 'description'), node('h3', 'Какие данные принимает'));
  const list = node('div', '', 'parameter-list');
  const header = node('div', '', 'parameter parameter-head');
  header.append(node('span','Параметр'),node('span','Тип данных'),node('span','Нужен для вызова')); list.append(header);
  for (const [name, value] of Object.entries(schema.properties || {})) {
    const row = node('div', '', 'parameter'); row.title = value.description || '';
    row.append(node('code',name),node('span',schemaType(value)),node('span',required.has(name) ? 'Обязательный' : 'Необязательный',required.has(name)?'required':'optional')); list.append(row);
  }
  if (!Object.keys(schema.properties || {}).length) list.append(node('p','Нет именованных параметров. Полная схема ниже.','hint'));
  detail.append(list, node('p', 'Это описание инструмента. Его вызов сейчас не выполняется.', 'hint'));
  const raw = node('details',''); raw.append(node('summary','Показать исходную JSON-схему'),node('pre',JSON.stringify(schema,null,2))); detail.append(raw);
  detail.scrollTop = 0;
}
$('search').addEventListener('input', renderTools);
$('server').addEventListener('change', () => {
  if (busy) return;
  clearResult(); describeProfile(); status('Сервер выбран');
  $('connect').textContent = 'Подключиться';
  $('connection-note').textContent = 'Нажмите «Подключиться», чтобы получить его инструменты.';
  $('events').replaceChildren(node('li','Пока нет событий.','muted'));
});
$('connect').addEventListener('click', async () => {
  if (busy) return;
  busy = true; clearResult(); $('connect').disabled = true; $('server').disabled = true;
  $('connect').textContent = 'Подключаемся…'; status('Получаем каталог…','busy');
  $('step-connect').className = 'step current';
  $('connection-note').textContent = 'Клиент запускает MCP-сервер и запрашивает доступные инструменты.';
  $('events').replaceChildren(node('li','Ожидаем ответ сервера…','muted'));
  try {
    const response = await fetch('/api/discover', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({server_id:$('server').value})});
    const data = await response.json(); renderEvents(data.events || []);
    if (!response.ok) throw new Error(data.error || 'Сервер не ответил');
    tools = data.tools; $('server-name').textContent = data.server.name;
    $('tool-count').textContent = tools.length; $('protocol').textContent = data.protocolVersion;
    $('transport').textContent = data.transport === 'stdio' ? 'Локально · stdio' : data.transport;
    for (const id of ['step-connect','step-init','step-list']) $(id).className = 'step done';
    status('Каталог получен','ok');
    $('connection-note').textContent = 'Соединение проверено. Сессия закрыта; ниже — полученный каталог. Его можно запросить повторно.';
    $('search').disabled = false; selected = tools[0]?.name || ''; renderTools();
    if (tools.length) renderDetail(tools[0]);
    else $('detail').replaceChildren(node('p','Соединение работает, но каталог сервера пуст.','empty'));
  } catch (error) {
    status('Не удалось подключиться','error');
    $('connection-note').textContent = `${error.message}. Проверьте сервер и повторите подключение.`;
    $('step-connect').className = 'step';
  } finally {
    busy = false; $('connect').disabled = false; $('server').disabled = false;
    $('connect').textContent = tools.length ? 'Обновить каталог' : 'Подключиться';
  }
});
async function boot() {
  try {
    const response = await fetch('/api/servers');
    if (!response.ok) throw new Error('Не удалось загрузить серверы');
    profiles = (await response.json()).servers;
    $('server').replaceChildren(...profiles.map(profile => {
      const option = node('option', profile.name + (profile.available ? '' : ' · не настроен'));
      option.value = profile.id; option.disabled = !profile.available; return option;
    }));
    const available = profiles.find(profile => profile.available);
    if (!available) throw new Error('Нет настроенных серверов');
    $('server').value = available.id; $('server').disabled = false; $('connect').disabled = false; describeProfile();
  } catch(error) { status('Ошибка загрузки','error'); $('connection-note').textContent = error.message; }
}
boot();
