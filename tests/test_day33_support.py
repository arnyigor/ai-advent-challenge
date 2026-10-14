"""Run day33 in its own interpreter to avoid cross-day top-level module collisions."""
import os
from pathlib import Path
import subprocess
import sys


def test_support_acceptance_with_real_mcp_and_isolated_database():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONIOENCODING='utf-8', DAY33_PROVIDER='gemini')
    result = subprocess.run([sys.executable, str(root / 'day33-support-assistant' / 'verify.py')],
        cwd=root, env=env, capture_output=True, text=True, encoding='utf-8', timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count('PASS:') == 11
