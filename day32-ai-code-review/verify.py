"""Run acceptance checks without executing code from the reviewed PR."""
import json
from pathlib import Path
import py_compile
import subprocess
import sys

DAY = Path(__file__).resolve().parent


def main():
    for name in ('review.py', 'demo.py', 'record_video.py', 'record_live_video.py', 'server.py', 'verify.py'):
        py_compile.compile(str(DAY/name), doraise=True)
    subprocess.run([sys.executable, '-m', 'pytest', str(DAY.parent/'tests/test_day32_review.py'),
                    str(DAY.parent/'tests/test_day31_providers.py'), '-q'], cwd=DAY.parent, check=True)
    result = json.loads((DAY/'evidence/result.json').read_text(encoding='utf-8'))
    demo = json.loads((DAY/'evidence/demo.json').read_text(encoding='utf-8'))
    assert result['finish_reason'] == 'STOP'
    assert {s['kind'] for s in demo['sources']} == {'code', 'documentation'}
    assert all(s in result['text'] for s in ('Потенциальные баги','Архитектурные проблемы','Рекомендации','pricing.py'))
    checks = {'syntax': 'passed', 'tests': 'passed', 'live_model': result['model'],
              'finish_reason': result['finish_reason'], 'rag_kinds': ['documentation','code'],
              'github_run': 'not performed', 'demo': demo['kind']}
    (DAY/'evidence/verification.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Acceptance passed; GitHub deployment remains unverified.')


if __name__ == '__main__':
    main()
