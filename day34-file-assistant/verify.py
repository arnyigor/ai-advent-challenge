"""Приёмочный прогон дня 34: три цели через реальный MCP и реальную модель.

Ничего не подменяется: ошибки модели/сети фиксируются как failed-критерии.
Результат — evidence/acceptance.json. Перед каждым сценарием проект
восстанавливается из baseline (воспроизводимость).
"""
import asyncio
import json
import re
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import DAY, reset_project, run_agent  # noqa: E402
from server import SCENARIOS  # noqa: E402

EVIDENCE = DAY / 'evidence'


def scenario_checks(scenario_id, result):
    steps = result['steps']
    tools = [s.get('tool') for s in steps if s['action'] == 'tool']
    answer = result['answer'].lower()
    changed = result['changed_files']
    if scenario_id == 'usage':
        return {
            'минимум 2 вызова инструментов': result['tool_calls'] >= 2,
            'использован поиск': 'search_files' in tools,
            'прочитан код': 'read_file' in tools,
            'в ответе есть pricing.py': 'pricing.py' in answer,
            'упомянуты другие файлы использования': ('cart.py' in answer or 'api.py' in answer),
            'файлы не изменены (задача на чтение)': changed == [],
        }
    if scenario_id == 'changelog':
        changelog = (DAY / 'sample_project' / 'CHANGELOG.md').read_text(encoding='utf-8')
        first_write = next((i for i, s in enumerate(steps)
                            if s.get('tool') in ('write_file', 'replace_in_file')), len(steps))
        reads = {s.get('arguments', {}).get('path') for s in steps[:first_write]
                 if s.get('tool') == 'read_file' and 'error' not in s}
        wrote_after_reading = 'CHANGELOG.md' in reads and any(
            path and path.endswith('.py') for path in reads)
        unreleased = re.search(r'## \[Unreleased\](.*?)(?=\n## |\Z)', changelog, re.S)
        return {
            'сначала чтение/поиск, потом запись': wrote_after_reading,
            'была запись в файл': any(t in ('write_file', 'replace_in_file') for t in tools),
            'CHANGELOG.md изменён': 'CHANGELOG.md' in changed,
            'запись про промокоды в Unreleased': bool(unreleased and
                re.search(r'промокод|promo', unreleased[1], re.I)),
            'session_diff непустой и про промокоды': bool(result['diff']) and
                ('промокод' in result['diff'].lower() or 'promo' in result['diff'].lower()),
        }
    if scenario_id == 'readme-check':
        readme = (DAY / 'sample_project' / 'README.md').read_text(encoding='utf-8')
        return {
            'была запись в файл': any(t in ('write_file', 'replace_in_file') for t in tools),
            'README.md изменён': 'README.md' in changed,
            'устаревшее утверждение о промокодах исправлено': 'Промокоды не поддерживаются' not in readme,
            'устаревший вызов API исправлен': 'calc.total(' not in readme and 'total_price(' in readme,
            'в ответе описано расхождение': ('устар' in answer or 'не соответств' in answer
                or 'промокод' in answer.lower()),
        }
    raise ValueError(scenario_id)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    EVIDENCE.mkdir(exist_ok=True)
    report = {'date': time.strftime('%Y-%m-%d %H:%M:%S'), 'scenarios': []}
    for scenario in SCENARIOS:
        reset_project()
        print(f'▶ {scenario["title"]}…', flush=True)
        entry = {'id': scenario['id'], 'goal': scenario['goal']}
        trace = []
        def on_step(step):
            trace.append(step)
            print('    ', step.get('tool', 'final'), flush=True)
            (EVIDENCE / f'{scenario["id"]}-partial.json').write_text(
                json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            result = asyncio.run(run_agent(scenario['goal'], on_step=on_step))
            (EVIDENCE / f'{scenario["id"]}-trace.json').write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            checks = scenario_checks(scenario['id'], result)
            entry.update(status='done', model=result['model'], steps=len(result['steps']),
                tool_calls=result['tool_calls'], duration_ms=result['duration_ms'],
                changed_files=result['changed_files'], answer=result['answer'],
                checks=checks, all_passed=all(checks.values()),
                tools_sequence=[s.get('tool', 'final') for s in result['steps']])
            print('  ', 'OK' if entry['all_passed'] else 'ЧАСТИЧНО', entry['tools_sequence'])
        except Exception as exc:
            entry.update(status='error', error=f'{type(exc).__name__}: {exc}', all_passed=False)
            print('   ОШИБКА:', entry['error'])
        report['scenarios'].append(entry)
    reset_project()
    report['all_passed'] = all(s['all_passed'] for s in report['scenarios'])
    (EVIDENCE / 'acceptance.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'all_passed': report['all_passed'],
                      'scenarios': {s['id']: s.get('all_passed') for s in report['scenarios']}},
                     ensure_ascii=False))
    return 0 if report['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
