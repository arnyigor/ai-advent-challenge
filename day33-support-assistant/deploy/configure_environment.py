"""Remote helper: receive provider environment on stdin, never print values."""
import json
import os
from pathlib import Path
import sys

target = Path(sys.argv[1]).resolve()
if target.name != 'service.env' or target.parent.name != 'day33':
    raise ValueError('Expected deploy/day33/service.env')
payload = json.load(sys.stdin)
allowed = {'GEMINI_API_KEY', 'OPENROUTER_API_KEY', 'WORMSOFT_API_KEY', 'DAY33_PROVIDER', 'DAY33_MODEL', 'DAY33_DAILY_LIMIT'}
if set(payload) - allowed:
    raise ValueError('Unexpected environment key')
if not any(payload.get(k) for k in ('GEMINI_API_KEY', 'OPENROUTER_API_KEY', 'WORMSOFT_API_KEY')):
    raise ValueError('Provider key missing')
lines = []
for key, value in payload.items():
    if not isinstance(value, str) or '\n' in value or '\r' in value or '\x00' in value:
        raise ValueError('Invalid environment value')
    # systemd EnvironmentFile double quoting (not a shell script).
    escaped = value.replace('\\', '\\\\').replace('"', '\\"')
    lines.append(f'{key}="{escaped}"')
target.parent.mkdir(parents=True, exist_ok=True)
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w', encoding='utf-8') as stream:
    stream.write('\n'.join(lines) + '\n')
os.chmod(target, 0o600)
print('Service environment configured; values hidden.')
