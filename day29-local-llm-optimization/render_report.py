"""Render saved experiments locally; never invoke a model."""
import argparse
from html import escape
import json
from pathlib import Path
import statistics


def render(paths):
    tables, answers = [], []
    for path in paths:
        report = json.loads(path.read_text(encoding='utf-8'))
        meta = report['metadata']
        for profile, summary in report['summary'].items():
            rows = [r for r in report['runs'] if r['profile'] == profile]
            quality = [r['manual_quality'] for r in rows if r.get('manual_quality') is not None]
            tokens = [r['usage']['completion_tokens'] for r in rows
                if isinstance(r.get('usage'), dict) and isinstance(r['usage'].get('completion_tokens'), int)]
            peaks = [r['cpu_resources']['sampled_peak_rss_bytes'] for r in rows
                if r.get('cpu_resources', {}).get('sampled_peak_rss_bytes') is not None]
            resources = dict(sampled_peak_rss_bytes=max(peaks)) if peaks else meta.get('resources', {})
            config = report.get('profiles', {}).get(profile, {})
            label = path.name + (' (прерван)' if meta.get('aborted') else '')
            settings = f"t={config.get('temperature', '—')}; max={config.get('max_tokens', '—')}; ctx={meta.get('context_window', '—')}; thinking={meta.get('reasoning', '—')}"
            cells = [label, profile, settings,
                str(len({r['case_id'] for r in rows})), str(max(r['repeat'] for r in rows)),
                str(summary['calls']), str(summary['nonempty']),
                str(summary['truncated']), str(round(summary['median_sec'], 2)) if summary['median_sec'] else '—',
                (str(round(resources['sampled_peak_rss_bytes']/1024**2)) + ('' if peaks else ' (общий)')) if resources.get('sampled_peak_rss_bytes') else '—',
                str(statistics.median(tokens)) if tokens else '—',
                str(round(statistics.mean(quality), 2)) if len(quality) == len(rows) else 'не оценено']
            tables.append('<tr>' + ''.join('<td>'+escape(c)+'</td>' for c in cells) + '</tr>')
            if config.get('system'):
                answers.append('<details><summary>'+escape(f'{path.name} / {profile}: system prompt')
                    + '</summary><pre>'+escape(config['system'])+'</pre></details>')
        for row in report['runs']:
            answers.append('<details><summary>' + escape(f"{path.name} / {row['profile']} / вопрос {row['case_id']} / повтор {row['repeat']}")
                + '</summary><p>'+escape(row['question'])+'</p><pre>'+escape(row.get('answer', row.get('error', '')))
                + '</pre><p>'+escape(row.get('quality_notes', ''))+'</p></details>')
        for case in meta.get('frozen_cases', []):
            answers.append('<details><summary>'+escape(f"{path.name}: источники вопроса {case['id']}")
                + '</summary><pre>'+escape(case['prepared']['prompt'])+'</pre></details>')
    return '<!doctype html><meta charset="utf-8"><title>День 29: CPU LLM</title><style>body{font:15px system-ui;margin:30px;max-width:1600px}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:7px}pre{white-space:pre-wrap}details{margin:14px 0}</style><h1>День 29: сохранённые реальные прогоны</h1><p>Медиана только успешных вызовов. RSS — максимум отсчётов процесса каждые 250 мс; не VRAM. Общий RSS относится ко всему эксперименту, если отдельные запросы не измерялись. Один повтор — пилот; прерванные и разные наборы не являются сопоставимыми полными прогонами. completion_tokens в reasoning on может включать рассуждение. Оценки 0–2 вручную, не независимая экспертиза.</p><table><tr><th>Отчёт</th><th>Профиль</th><th>t / max_tokens</th><th>Вопросы</th><th>Повторы</th><th>Вызовы</th><th>Непустые</th><th>Обрезаны</th><th>Медиана, с</th><th>RSS, MiB</th><th>Медиана completion_tokens</th><th>Качество</th></tr>' + ''.join(tables) + '</table><h2>Ответы и исходный контекст</h2>' + ''.join(answers)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('reports', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent / 'results/report.html')
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(args.reports), encoding='utf-8')
    print(args.output)
