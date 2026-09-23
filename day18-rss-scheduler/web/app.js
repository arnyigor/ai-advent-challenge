const $ = id => document.getElementById(id);
const time = value => value ? new Date(value).toLocaleString('ru-RU') : '—';

async function refresh() {
  const response = await fetch('/api/state');
  const data = await response.json();
  const last = data.status.last_run;
  $('count').textContent = data.status.articles;
  $('downloaded').textContent = last ? `${last.found} статей` : '—';
  $('new-count').textContent = last ? last.inserted : '—';
  $('model').textContent = data.digest?.provider === 'plain' ? 'RSS-резерв' : data.digest?.model || '—';
  $('summary').textContent = data.digest?.body || 'Сводка ещё не создана.';
  $('digest-meta').textContent = data.digest
    ? `${time(data.digest.created_at)} · ${data.digest.article_count} публикаций · ${data.digest.provider === 'plain' ? 'без модели' : data.digest.provider}`
    : 'После сбора нажмите «Создать сводку».';

  const attempts = $('attempts');
  attempts.replaceChildren();
  for (const item of data.digest?.attempts || []) {
    const chip = document.createElement('span');
    chip.className = item.result;
    const outcome = item.result === 'ok' ? 'успех' : item.result === 'failed'
      ? data.simulation ? 'эмуляция отказа' : item.error || 'ошибка' : 'нет ключа';
    chip.textContent = `${item.provider}: ${outcome}`;
    attempts.append(chip);
  }

  for (const job of ['collect', 'digest']) {
    const item = data.schedule_active ? data.schedule.find(entry => entry.job === job) : null;
    $(job + '-schedule').textContent = item
      ? `Каждые ${item.interval_seconds} сек · следующий: ${time(item.next_at)} · ${item.last_result || 'ожидает запуска'}`
      : 'Планировщик выключен';
  }

  const articles = $('articles');
  articles.replaceChildren();
  for (const item of data.articles) {
    const link = document.createElement('a');
    link.href = item.url;
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = item.title;
    const date = document.createElement('small');
    date.textContent = item.published;
    link.append(date);
    articles.append(link);
  }

  const runs = $('runs');
  runs.replaceChildren();
  if (!data.runs.length) runs.textContent = 'Загрузок ещё не было.';
  for (const run of data.runs) {
    const row = document.createElement('div');
    row.textContent = `${time(run.ran_at)} · RSS: ${run.found} · новых: ${run.inserted}${run.error ? ' · ошибка: ' + run.error : ''}`;
    runs.append(row);
  }
  if (data.simulation) $('status').textContent = 'Демо: отказы моделей эмулируются; RSS и SQLite работают реально.';
}

async function run(action) {
  for (const id of ['reset', 'collect', 'digest']) $(id).disabled = true;
  $('status').textContent = action === 'collect' ? 'Загружаю RSS…' : action === 'digest' ? 'Создаю сводку…' : 'Сбрасываю данные дня 18…';
  try {
    const response = await fetch('/api/' + action, {method: 'POST'});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Ошибка');
    $('status').textContent = action === 'collect'
      ? `RSS загружен: ${data.found} статей, ${data.inserted} новых записей`
      : action === 'digest' ? `Сводка сохранена: ${data.provider} / ${data.model || 'RSS-резерв'}`
      : 'Состояние сброшено: статьи, загрузки и сводки удалены.';
    await refresh();
  } catch (error) {
    $('status').textContent = error.message;
  } finally {
    for (const id of ['reset', 'collect', 'digest']) $(id).disabled = false;
  }
}

$('reset').onclick = () => run('reset');
$('collect').onclick = () => run('collect');
$('digest').onclick = () => run('digest');
refresh().catch(error => { $('status').textContent = error.message; });
setInterval(() => refresh().catch(() => {}), 2000);
