const el = id => document.getElementById(id);
fetch('/api/config').then(r => r.json()).then(c => {
  el('config').textContent = `${c.index.chunks} фрагментов · ${c.index.embedding_model} · LLM: ${c.model}`;
}).catch(() => { el('config').textContent = 'Не удалось прочитать настройки'; });
async function run(searchOnly) {
  el('ask').disabled = el('retrieve').disabled = true;
  el('status').textContent = searchOnly ? 'Локальный поиск…' : 'Поиск и ожидание локальной модели…';
  try {
    const response = await fetch(searchOnly ? '/api/retrieve' : '/api/ask', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: el('question').value}),
    });
    const data = await response.json();
    if (!response.ok) throw Error(data.error);
    el('answer').textContent = data.answer || 'Выполнен только поиск. Генерация не запускалась.';
    el('metrics').textContent = `Поиск: ${data.retrieval_sec} с` + (searchOnly ? '' :
      ` · Генерация: ${data.generation_sec} с · ${data.model} · Завершение: ${data.finish_reason || 'неизвестно'}`);
    el('sources').replaceChildren();
    for (const source of data.sources) {
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = `[${source.rank}] ${source.source} / ${source.section} · ${source.score}`;
      const text = document.createElement('pre'); text.textContent = source.text;
      details.append(summary, text); el('sources').append(details);
    }
    el('status').textContent = searchOnly ? 'Поиск завершён.' : data.finish_reason === 'length' ?
      'Ответ обрезан лимитом генерации.' : data.answer_status === 'unknown' && data.citation_ids_valid ?
      'Модель сообщила: в найденных документах недостаточно данных.' : !data.has_citations || !data.citation_ids_valid ?
      'Проверьте ответ: отсутствуют ссылки или указаны неизвестные номера.' : 'Готово. Сверьте утверждения с фрагментами.';
  } catch (error) { el('status').textContent = error.message; }
  finally { el('ask').disabled = el('retrieve').disabled = false; }
}
el('ask').onclick = () => run(false);
el('retrieve').onclick = () => run(true);
