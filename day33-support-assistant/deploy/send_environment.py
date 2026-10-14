"""Local helper: current environment → SSH stdin, no secret in argv/output."""
import json
import os
from pathlib import Path
import re
import subprocess
from argparse import ArgumentParser

parser = ArgumentParser()
parser.add_argument('--target', required=True, help='SSH user@host')
parser.add_argument('--key', type=Path, required=True)
parser.add_argument('--app-dir', required=True)
args = parser.parse_args()
if not re.fullmatch(r'[a-zA-Z0-9_.@-]+', args.target) or not re.fullmatch(r'/[a-zA-Z0-9_./-]+', args.app_dir):
    raise ValueError('Invalid target/path')
provider = os.environ.get('DAY33_PROVIDER', 'gemini')
key_name = {'gemini': 'GEMINI_API_KEY', 'openrouter': 'OPENROUTER_API_KEY', 'wormsoft': 'WORMSOFT_API_KEY'}[provider]
key = os.environ.get(key_name, '').strip()
if not key:
    raise ValueError('Selected provider key must be present in local process environment')
config = str(Path(args.app_dir).parent.as_posix()) + '/deploy/day33/service.env'
payload = {key_name: key, 'DAY33_PROVIDER': provider,
    'DAY33_DAILY_LIMIT': os.environ.get('DAY33_DAILY_LIMIT', '200')}
if os.environ.get('DAY33_MODEL'):
    payload['DAY33_MODEL'] = os.environ['DAY33_MODEL']
subprocess.run(['ssh', '-o', 'BatchMode=yes', '-i', str(args.key), args.target,
    f'python3 {args.app_dir}/deploy/configure_environment.py {config}'],
    input=json.dumps(payload), text=True, check=True)
