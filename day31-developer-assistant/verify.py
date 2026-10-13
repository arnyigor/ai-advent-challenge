"""Real E5 + MCP + LLM acceptance; saves actual answers, never canned ones."""
import json
from pathlib import Path
import subprocess
import sys

from assistant import Assistant
from project_index import inspect_index

QUESTIONS = [
    '/help Как устроен проект и где находятся RAG и MCP?',
    '/help Как проходит запрос /help и какие поля возвращает API?',
    '/help Какая сейчас git-ветка проекта?',
    '/help Какова выручка проекта за 2025 год?',
    '/help Сколько платных подписчиков было у проекта на 1 сентября 2026 года?',
]


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    day = Path(__file__).resolve().parent
    service = Assistant()
    report = {'index': inspect_index(), 'calls': [], 'checks': {}, 'manual_review': 'pending'}
    target = day / 'evidence' / 'acceptance.json'
    target.parent.mkdir(exist_ok=True)
    for command in QUESTIONS:
        print(command, flush=True)
        result = service.help(command)
        result.pop('prompt', None)
        report['calls'].append({'command': command, **result})
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(result['answer'], flush=True)
    branch = subprocess.check_output(['git', '-C', str(service.pipeline.root), 'branch', '--show-current'], encoding='utf-8').strip()
    report['checks'] = {
        'root_readme_indexed': 'README.md' in report['index']['sources'],
        'docs_indexed': any(p.startswith('docs/') for p in report['index']['sources']),
        'semantic_model': report['index']['embedding_model'] == 'intfloat/multilingual-e5-small',
        'live_branch_matches': all(c['project']['branch'] == (branch or '(detached HEAD)') for c in report['calls']),
        'real_mcp': all(c['mcp']['steps'] == ['initialize', 'tools/list', 'tools/call'] for c in report['calls']),
        'not_truncated': all(c['finish_reason'] != 'length' for c in report['calls']),
        'citation_numbers_valid': all(c['citation_ids_valid'] for c in report['calls']),
        'structure_has_citations': report['calls'][0]['has_citations'],
        'api_has_citations': report['calls'][1]['has_citations'],
        'unknown_refusal': all('недостаточно данных' in c['answer'].casefold() for c in report['calls'][3:]),
    }
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['checks'], ensure_ascii=False, indent=2))
    return 0 if all(report['checks'].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
