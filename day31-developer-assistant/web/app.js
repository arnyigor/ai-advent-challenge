const $ = (id) => document.getElementById(id);
window.lastResult = null;
fetch('/api/config').then(async (r) => {
  if (!r.ok) throw new Error('Ошибка чтения индекса');
  const c = await r.json();
  $('config').textContent = `${c.index.documents} документов · ${c.index.chunks} чанков · ${c.index.embedding_model} · LLM: ${c.model}`;
}).catch((e) => { $('config').textContent = e.message; });
for (const button of document.querySelectorAll('[data-command]')) {
  button.addEventListener('click', () => { $('command').value = button.dataset.command; });
}
$('form').addEventListener('submit', async (e) => {
  e.preventDefault();
  $('submit').disabled = true;
  $('status').textContent = 'Читаем ветку через MCP → находим документы → получаем ответ…';
  $('answer').textContent = 'Выполняется новый запрос…';
  $('metrics').textContent = '';
  $('branch').textContent = 'Чтение Git…';
  $('head').textContent = '';
  $('mcp').textContent = '';
  $('sources').replaceChildren();
  window.lastResult = null;
  try {
    const response = await fetch('/api/help', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({command: $('command').value})});
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
    window.lastResult = value;
    $('answer').textContent = value.answer;
    $('branch').textContent = value.project.branch;
    $('head').textContent = `${value.project.repository} · HEAD ${value.project.head.slice(0, 12)}`;
    $('mcp').textContent = JSON.stringify({steps: value.mcp.steps, tool: value.mcp.tool,
      arguments: value.mcp.arguments, result: value.mcp.result, server: value.mcp.server}, null, 2);
    $('metrics').textContent = `Поиск ${value.retrieval_sec.toFixed(2)} с · генерация ${value.generation_sec.toFixed(2)} с · ${value.model} · finish: ${value.finish_reason} · ссылки ${value.citation_ids_valid ? 'в диапазоне' : 'ошибочные'}${value.has_citations ? '' : ', в ответе нет ссылок'}`;
    if (value.finish_reason === 'length') $('metrics').textContent += ' · ВНИМАНИЕ: ответ обрезан';
    for (const source of value.sources) {
      const detail = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = `[${source.rank}] ${source.source} · ${source.section}`;
      const text = document.createElement('pre');
      text.textContent = source.text;
      detail.append(summary, text);
      $('sources').append(detail);
    }
    $('status').textContent = 'Готово. Сверьте ответ с найденными фрагментами.';
  } catch (error) {
    $('answer').textContent = error.message;
    $('branch').textContent = 'Нет результата';
    $('status').textContent = 'Запрос завершился ошибкой';
  } finally { $('submit').disabled = false; }
});
