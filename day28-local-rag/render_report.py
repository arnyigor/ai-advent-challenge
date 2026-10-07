"""Render saved real benchmark results, never perform inference."""
import html
import json
from pathlib import Path
from rag import DAY


def render(paths):
    escape = lambda value: html.escape(str(value))
    sections = []
    for path in paths:
        report = json.loads(Path(path).read_text(encoding='utf-8'))
        provider_labels = {'local':'Strata / Qwen3.8', 'cloud':'DeepSeek V4 Flash'}
        summary = ''.join(f'<tr><td>{escape(provider_labels.get(name,name))}</td><td>{s["successful"]}/{s["requests"]}</td>'
                         f'<td>{escape(s.get("truncated") if s.get("truncated") is not None else "неизвестно")}</td>'
                         f'<td>{s["median_generation_sec"]:.2f} с</td><td>{s["p95_generation_sec"]:.2f} с</td>'
                         f'<td>{s.get("quality_mean_0_to_2", "не оценено")}</td></tr>'
                         for name, s in report['summary'].items() if s['median_generation_sec'] is not None)
        groups = {}
        for row in report['runs']:
            groups.setdefault(row['question'], []).append(row)
        questions = []
        for question, rows in groups.items():
            answers = []
            for name in report['summary']:
                subset = [r for r in rows if r['provider'] == name]
                first = next((r for r in subset if r['ok']), subset[0])
                grades = ', '.join(str(r.get('manual_quality')) for r in subset)
                answers.append(f'<article><h3>{escape(provider_labels.get(name,name))} · оценки: {escape(grades)}</h3>'
                               f'<pre>{escape(first.get("answer", first.get("error")))}</pre>'
                               f'<p>{escape(first.get("notes", ""))}</p></article>')
            questions.append(f'<details><summary>{escape(question)}</summary>{"".join(answers)}</details>')
        label = {'comparison':'Базовый поиск', 'complex':'Сложные запросы', 'regression':'Перепроверка длинных ответов'}.get(Path(path).stem, Path(path).stem)
        word = 'вопрос' if len(groups)==1 else 'вопросов'
        title = f'{label}: {len(groups)} {word} × {max(r["repeat"] for r in report["runs"])} повтора'
        config = report.get('generation_config', {})
        mode = report.get('retrieval_config', {}).get('mode') or report['runs'][0].get('retrieval_mode')
        sections.append(f'<section><h2>{escape(title)}</h2><p>Retrieval: {escape(mode)} · '
                        f'Бюджет: {escape(config.get("max_tokens"))} токенов</p><table><tr><th>Модель</th>'
                        f'<th>Непустые</th><th>Обрезаны</th><th>Медиана</th><th>p95</th><th>Качество / 2</th></tr>{summary}</table>'
                        f'{"".join(questions)}</section>')
    network_path = DAY / 'results/local-network-check.json'
    if network_path.is_file():
        network = json.loads(network_path.read_text(encoding='utf-8'))
        sections.append('<section><h2>Проверка локальности процесса RAG</h2>'
                        f'<p>Защита активна: {escape(network["guard_active"])}. '
                        f'Внешних попыток приложения: {len(network["blocked_application_attempts"])}.</p>'
                        f'<pre>{escape(json.dumps(network["connections"], ensure_ascii=False, indent=2))}</pre>'
                        f'<p>{escape(network["result"]["answer"])}</p>'
                        '<p>Ограничены соединения Python RAG. Сеть ОС и отдельного процесса Strata не отключалась.</p></section>')
    target = DAY / 'results/report.html'
    target.write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><title>День 28 · Реальные результаты</title>'
                      '<link rel="stylesheet" href="/style.css"><main><h1>Локальный RAG: сравнение моделей</h1>'
                      '<p>Реальные ответы, одинаковый контекст. Оценки 0–2 после сверки агентом с источниками. '
                      'Задержки включают API и генерацию; модели и настройки reasoning различаются.</p>'
                      + ''.join(sections) + '</main></html>', encoding='utf-8')
    print(target)


if __name__ == '__main__':
    import sys
    render(sys.argv[1:] or [DAY / 'results/comparison.json', DAY / 'results/complex.json'])
