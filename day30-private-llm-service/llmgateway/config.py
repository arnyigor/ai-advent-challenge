"""Day 30 gateway configuration: the single source of truth for the API contract.

Every limit that the gateway enforces is declared here once and is reused by the
gateway, the check script (verify.py) and the README table. Values come from the
environment; nothing is duplicated elsewhere.

Backend endpoints used (verified against llama-server build 11054):
  GET  /health         - readiness, no model path
  GET  /v1/models      - alias list
  POST /apply-template - chat template rendering
  POST /tokenize       - exact token count for the rendered prompt
  POST /v1/chat/completions
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DAY_DIR = PACKAGE_DIR.parent
KEYS_FILE_DEFAULT = DAY_DIR / "keys.json"
MODEL_KEY_FILE_DEFAULT = DAY_DIR / "model-key.txt"

# --- backend and bind -------------------------------------------------------
MODEL_ALIAS = os.environ.get("MODEL_ALIAS", "day30-qwen3-1.7b")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8081").rstrip("/")
SERVICE_HOST = os.environ.get("SERVICE_HOST", "127.0.0.1")
SERVICE_PORT = int(os.environ.get("SERVICE_PORT", "8091"))

# --- execution profile (must match run-model.bat, checked at startup) -------
CONTEXT_WINDOW = 4096
PARALLEL_SLOTS = 1
THREADS = 8

# --- POST /v1/chat/completions contract ------------------------------------
CONTEXT_MARGIN_TOKENS = 32
MAX_BODY_BYTES = 64 * 1024
MIN_MAX_TOKENS = 1
MAX_MAX_TOKENS = 1024
DEFAULT_MAX_TOKENS = 256
CLIENT_ROLES = ("user", "assistant")
MAX_MESSAGES = 64

# --- limits -----------------------------------------------------------------
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW_SEC = 60.0
MAX_WAITING_REQUESTS = 3
QUEUE_WAIT_TIMEOUT_SEC = 60.0
GENERATION_TIMEOUT_SEC = 120.0
CONNECT_TIMEOUT_SEC = 5.0

# The gateway owns the system message; clients send only user/assistant turns.
SYSTEM_PROMPT = (
    "Ты локальный ассистент домашнего сервиса. Отвечай кратко, по-русски, "
    "по существу. Не выдумывай факты: если чего-то не знаешь, скажи об этом прямо."
)

ACCESS_LOG_DEFAULT = DAY_DIR / "evidence" / "access.log"


def model_api_key() -> str:
    """Key that protects llama-server itself (llama-server --api-key).

    Optional but recommended: with it set, the gateway is the only holder and a
    local process cannot call the model directly. Empty means an open loopback
    backend; llama-server prints its own warning in that case.
    """
    key = os.environ.get("MODEL_API_KEY", "").strip()
    if key:
        return key
    path = Path(os.environ.get("MODEL_KEY_FILE", str(MODEL_KEY_FILE_DEFAULT)))
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


def load_keys() -> dict:
    """Return {label: key} from SERVICE_API_KEYS or from the keys file.

    SERVICE_API_KEYS format: "main=KEY1;ratelimit=KEY2". The keys file is a JSON
    object {label: key}. Secrets stay outside Git (keys.json is ignored).
    """
    raw = os.environ.get("SERVICE_API_KEYS", "").strip()
    if raw:
        keys = {}
        for chunk in raw.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            label, sep, value = chunk.partition("=")
            if not sep or not label.strip() or not value.strip():
                raise RuntimeError('SERVICE_API_KEYS must look like "label=key;label2=key2"')
            keys[label.strip()] = value.strip()
        if keys:
            return keys
    path = Path(os.environ.get("SERVICE_KEYS_FILE", str(KEYS_FILE_DEFAULT)))
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        keys = {str(label): str(value) for label, value in data.items() if str(value).strip()}
        if keys:
            return keys
    raise RuntimeError(
        f"no API keys configured: set SERVICE_API_KEYS or create {path} "
        '(JSON object {"main": "<key>"}); see README section "Ключи доступа"'
    )
