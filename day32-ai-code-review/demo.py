"""Create an isolated two-commit example and run the real reviewer."""
import argparse
import json
from pathlib import Path
import subprocess
from review import run

DAY = Path(__file__).resolve().parent


def fixture(repo):
    if repo.exists():
        raise ValueError('Demo directory already exists; choose a new --repo')
    repo.mkdir(parents=True)
    def cmd(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()
    cmd('init')
    cmd('config', 'user.name', 'Day32 local demo')
    cmd('config', 'user.email', 'demo@example.invalid')
    (repo/'docs').mkdir()
    (repo/'docs/architecture.md').write_text('# Checkout contract\nCheckout totals are computed by checkout.total using pricing.discount.\nA discount is a percent between 0 and 100. Prices and totals must never become negative.\nValidation belongs in pricing; callers rely on that contract.\n', encoding='utf-8')
    (repo/'pricing.py').write_text('def discount(price, percent):\n    if not 0 <= percent <= 100:\n        raise ValueError("invalid percent")\n    return price * (1 - percent / 100)\n', encoding='utf-8')
    (repo/'checkout.py').write_text('from pricing import discount\n\ndef total(items, percent):\n    return sum(discount(price, percent) for price in items)\n', encoding='utf-8')
    cmd('add', '.')
    cmd('commit', '-m', 'Base: validated percentage discount')
    base = cmd('rev-parse', 'HEAD')
    (repo/'pricing.py').write_text('def discount(price, percent):\n    return price * (1 - percent)\n', encoding='utf-8')
    cmd('add', '.')
    cmd('commit', '-m', 'PR: simplify discount calculation')
    return base, cmd('rev-parse', 'HEAD')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=DAY/'evidence/demo-repo')
    parser.add_argument('--retrieve-only', action='store_true')
    args = parser.parse_args()
    base, head = fixture(args.repo)
    payload = run(args.repo, base, head, DAY/'evidence', args.retrieve_only)
    (DAY/'evidence/demo.json').write_text(json.dumps({'kind': 'local two-commit PR simulation, not GitHub run',
        'base': base, 'head': head, 'sources': payload['sources'], 'changed_paths': payload['changed_paths']}, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
