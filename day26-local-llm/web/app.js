// UI Дня 26: показывает реальные HTTP-ответы локальной Strata. Никаких заготовок.
const $ = (id) => document.getElementById(id);

function line(text, cls = '') {
  const el = document.createElement('div');
  el.className = cls;
  el.textContent = text;
  $('lines').append(el);
  const box = $('lines');
  while (box.children.length > 6) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
}

function card(data) {
  const el = document.createElement('article');
  el.className = 'card grow';
  el.dataset.state = data.error ? 'error' : 'done';
  const head = document.createElement('h2');
  head.textContent = data.title;
  const q = document.createElement('p');
  q.className = 'q';
  q.textContent = 'Запрос: ' + data.prompt;
  const a = document.createElement('pre');
  a.className = 'a';
  a.textContent = data.error ? 'Ошибка: ' + data.error : data.answer;
  const f = document.createElement('div');
  f.className = 'f';
  f.textContent = data.error
    ? 'Ответа нет · обработка продолжена'
    : `${data.elapsedMs} мс · модель ответа: ${data.returnedModel ?? 'не указана'} · finish_reason: ${data.finishReason ?? 'не указан'} · ${data.validation} · usage: ${JSON.stringify(data.usage ?? null)}`;
  el.append(head, q, a, f);
  return el;
}

async function main() {
  let status;
  try {
    status = await (await fetch('/api/status')).json();
  } catch (error) {
    $('health').textContent = 'нет связи со стендом';
    line('ERROR ' + error.message, 'e');
    return;
  }
  $('endpoint').textContent = status.base;
  $('model').textContent = status.model;
  $('cmd').textContent = `POST ${status.base}/chat/completions   { "model": "${status.model}", "messages": [...], "stream": false }`;
  if (status.ok) {
    $('health').textContent = 'отвечает';
    $('health').className = 'ok';
    line(`GET ${status.base}/models → 200 · доступно моделей: ${status.models.length}`, 'g');
    for (const m of status.models) {
      const li = document.createElement('li');
      li.textContent = `${m.id} · ${m.status ?? 'нет статуса'} · ctx ${m.ctx ?? '—'}`;
      $('models').append(li);
      line(`модель ${m.id} · статус ${m.status ?? '—'} · контекст ${m.ctx ?? '—'}`, 'g');
    }
  } else {
    $('health').textContent = 'ошибка: ' + status.error;
    line(`GET ${status.base}/models → ${status.error}`, 'e');
  }

  const cases = await (await fetch('/api/cases')).json();
  $('run').disabled = false;
  $('run').addEventListener('click', async () => {
    $('run').disabled = true;
    $('cards').innerHTML = '';
    const collected = [];
    for (const item of cases) {
      $('reportbar').hidden = true;
      const pending = document.createElement('article');
      pending.className = 'card';
      pending.dataset.state = 'running';
      pending.innerHTML = `<h2>${item.title}</h2>`;
      const q = document.createElement('p');
      q.className = 'q';
      q.textContent = 'Запрос: ' + item.prompt;
      const a = document.createElement('pre');
      a.className = 'a';
      pending.append(q, a);
      $('cards').append(pending);
      const started = performance.now();
      // Живой счётчик: видно, что ожидание идёт в реальном времени.
      const tick = () => {a.textContent = `модель генерирует… ${((performance.now() - started) / 1000).toFixed(1)} с`;};
      tick();
      const timer = setInterval(tick, 250);
      line(`POST ${status.base}/chat/completions · ${item.id} · отправлен`, 'w');
      let data;
      try {
        data = await (await fetch('/api/ask', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({id: item.id})})).json();
      } catch (error) {
        data = {...item, error: error.message};
      }
      clearInterval(timer);
      const wall = Math.round(performance.now() - started);
      if (!data.error && !data.answer) data.error = 'пустой ответ'; // считать успехом нечего
      collected.push(data);
      $('cards').replaceChild(card(data), pending);
      if (data.error) line(`← ошибка: ${data.error} · ${wall} мс`, 'e');
      else line(`← 200 · ${data.elapsedMs} мс · finish=${data.finishReason} · ${data.validation}`, 'g');
    }
    // Сохраняем отчёт именно этого прогона; ссылку показываем в интерфейсе.
    try {
      const response = await fetch('/api/report', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({results: collected})});
      const saved = await response.json();
      if (!response.ok || !/^\/report\/[\w.-]+$/.test(saved.url ?? '')) throw Error(saved.error || `HTTP ${response.status}`);
      line(`отчёт: ${saved.url}`, 'g');
      $('report-link').href = saved.url;
      $('reportbar').hidden = false;
    } catch (error) {
      line('отчёт не сохранён: ' + error.message, 'e');
    }
    $('run').disabled = false;
    $('run').textContent = 'Прогнать ещё раз';
  });
}

main();
