"""One configuration contract shared by API, MCP and deployment."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

DAY = Path(__file__).resolve().parent
DATA = Path(os.environ.get('DAY33_DATA_DIR', DAY / 'data')).resolve()
CRM = Path(os.environ.get('DAY33_CRM_PATH', DAY / 'fixtures' / 'crm.json')).resolve()
KNOWLEDGE = Path(os.environ.get('DAY33_KNOWLEDGE_DIR', DAY / 'knowledge')).resolve()
PROVIDER = os.environ.get('DAY33_PROVIDER', 'gemini')
if PROVIDER not in {'gemini', 'openrouter', 'wormsoft'}:
    raise ValueError('DAY33_PROVIDER: gemini, openrouter or wormsoft')
WORMSOFT_URL = ''
if PROVIDER == 'wormsoft':
    # Reuse the working day18 provider contract, rather than copying its defaults.
    import sys
    sys.path.insert(0, str(DAY.parent / 'day18-rss-scheduler'))
    from day18_providers import WORMSOFT_MODEL, WORMSOFT_URL
    DEFAULT_MODEL = WORMSOFT_MODEL
else:
    DEFAULT_MODEL = 'gemini-3.5-flash-lite' if PROVIDER == 'gemini' else 'openrouter/free'
MODEL = os.environ.get('DAY33_MODEL', DEFAULT_MODEL)
HOST = os.environ.get('DAY33_HOST', '127.0.0.1')
PORT = int(os.environ.get('DAY33_PORT', '8833'))
TIMEZONE = ZoneInfo(os.environ.get('DAY33_TIMEZONE', 'Asia/Yekaterinburg'))
DAILY_LIMIT = int(os.environ.get('DAY33_DAILY_LIMIT', '200'))
SECURE_COOKIE = os.environ.get('DAY33_SECURE_COOKIE', '0') == '1'
