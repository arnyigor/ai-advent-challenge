const $ = id => document.getElementById(id);
const time = value => value ? new Intl.DateTimeFormat('ru-RU', {timeZone:'Asia/Yekaterinburg', day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'}).format(new Date(value)) + ' ЕКБ' : '—';
function set(id, value) { $(id).textContent = value; }

function render(data) {
  const last = data.status.last_run;
  const digest = data.digest;
  set('articles-count', data.status.articles);
  set('last-found', last ? last.found : '—');
  set('last-new', last ? last.inserted : '—');
  set('last-collect-time', last ? time(last.ran_at) : 'Сбор ещё не запускался');
  set('digest-count', digest ? digest.article_count + ' статей' : '—');
  set('digest-time', digest ? time(digest.created_at) : 'Сводки пока нет');
  set('next-collect', 'Следующий запуск: ' + time(data.schedule.collect));
  set('next-digest', 'Следующий запуск: ' + time(data.schedule.digest));
  set('digest-meta', digest ? `Сохранено ${time(digest.created_at)} · источник: ${digest.provider === 'plain' ? 'RSS без модели' : digest.provider} · ${digest.article_count} публикаций` : 'Сводка появится после первого запуска.');
  set('digest-body', digest ? digest.body : 'Сводки пока нет.');
  set('checked-at', 'Проверено: ' + time(data.checked_at));

  const articleList = $('article-list'); articleList.replaceChildren();
  for (const item of data.articles) {
    let url; try { url = new URL(item.url); } catch { continue; }
    if (url.protocol !== 'https:' || !['habr.com', 'www.habr.com'].includes(url.hostname)) continue;
    const a = document.createElement('a'); a.href = url.href; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = item.title;
    articleList.append(a);
  }
  if (!articleList.childElementCount) articleList.textContent = 'Публикаций пока нет.';

  const runList = $('run-list'); runList.replaceChildren();
  for (const run of data.runs) {
    const row = document.createElement('div'); row.className = 'run';
    const when = document.createElement('span'); when.textContent = time(run.ran_at);
    const result = document.createElement('b'); result.textContent = run.error ? 'Ошибка' : `${run.found} получено · ${run.inserted} новых`;
    row.append(when, result); runList.append(row);
  }
  if (!runList.childElementCount) runList.textContent = 'Сборов пока нет.';
}

async function refresh() {
  try {
    const response = await fetch('/api/state', {cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) { set('checked-at', 'Ошибка обновления: ' + error.message); }
}
refresh(); setInterval(refresh, 30000);
