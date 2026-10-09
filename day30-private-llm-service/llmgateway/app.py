"""Day 30 HTTP gateway.

Public contract (all limits come from config.py):

  GET  /health              - readiness of the backend, no secrets, 503 when down
  GET  /limits              - the numbers the chat UI displays
  GET  /v1/models           - authorized, single fixed alias
  POST /v1/chat/completions - authorized, JSON error contract

The gateway never proxies arbitrary llama.cpp endpoints, never logs prompts or
answers, and keeps its own system message.
"""
from __future__ import annotations

import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

from . import config
from .backend import Backend, BackendStatusError, BackendTimeout, BackendUnavailable
from .limits import GenerationQueue, QueueFullError, QueueTimeoutError, SlidingWindowLimiter

STATIC_DIR = Path(__file__).resolve().parent / "static"
FORBIDDEN_GENERATION_KEYS = (
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "seed",
    "enable_thinking",
    "chat_template_kwargs",
    "reasoning_format",
)


class ContractError(Exception):
    """Request rejected by the gateway contract before touching the backend."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class AccessLog:
    """One JSON line per request: ids, timings, status, usage. No prompts."""

    def __init__(self, path=None, stream=None):
        self.path = Path(path) if path else None
        self._stream = stream

    def write(self, record):
        line = json.dumps(record, ensure_ascii=False)
        stream = self._stream
        if stream is None:
            import sys

            stream = sys.stdout
        try:
            print(line, file=stream, flush=True)
        except Exception:  # logging must never break a request
            pass
        if self.path:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:
                pass


def new_request_id():
    return "req-" + uuid.uuid4().hex[:12]


def error_response(status, code, message, request_id, retry_after=None):
    headers = {"x-request-id": request_id}
    if retry_after is not None:
        headers["retry-after"] = str(max(int(round(retry_after)), 1))
    if status == 401:
        headers["www-authenticate"] = "Bearer"
    return JSONResponse(
        {"error": {"code": code, "message": message, "request_id": request_id}},
        status_code=status,
        headers=headers,
    )


def bearer_token(request):
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def authorize(request, keys):
    token = bearer_token(request)
    if not token:
        return None, "Authorization: Bearer <key> is required"
    for label, key in keys.items():
        if hmac.compare_digest(token, key):
            return label, None
    return None, "unknown API key"


async def read_body(request, limit):
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise ContractError(413, "payload_too_large", f"body larger than {limit} bytes")
        except ValueError:
            raise ContractError(400, "invalid_request", "malformed content-length") from None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise ContractError(413, "payload_too_large", f"body larger than {limit} bytes")
    return bytes(body)


def validate_chat_request(payload):
    """Return (messages for the backend, max_tokens) or raise ContractError."""
    if not isinstance(payload, dict):
        raise ContractError(400, "invalid_request", "тело запроса должно быть JSON-объектом")
    model = payload.get("model")
    if model != config.MODEL_ALIAS:
        raise ContractError(
            400, "unknown_model", f'неизвестная модель "{model}"; доступна только "{config.MODEL_ALIAS}"'
        )
    if payload.get("stream") not in (None, False):
        raise ContractError(400, "invalid_request", "stream=true не поддерживается в этой версии")
    for key in FORBIDDEN_GENERATION_KEYS:
        if key in payload:
            raise ContractError(
                400, "invalid_request", f'параметр "{key}" задаёт сервер и не принимается от клиента'
            )
    max_tokens = payload.get("max_tokens", config.DEFAULT_MAX_TOKENS)
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
        raise ContractError(400, "invalid_max_tokens", "max_tokens должен быть целым числом")
    if not config.MIN_MAX_TOKENS <= max_tokens <= config.MAX_MAX_TOKENS:
        raise ContractError(
            400,
            "invalid_max_tokens",
            f"max_tokens должен быть в диапазоне {config.MIN_MAX_TOKENS}..{config.MAX_MAX_TOKENS}",
        )
    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        raise ContractError(400, "invalid_messages", "messages должен быть непустым списком")
    if len(raw_messages) > config.MAX_MESSAGES:
        raise ContractError(400, "invalid_messages", f"не больше {config.MAX_MESSAGES} сообщений")
    messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]
    for index, item in enumerate(raw_messages):
        if not isinstance(item, dict):
            raise ContractError(400, "invalid_messages", f"messages[{index}] должен быть объектом")
        role = item.get("role")
        if role == "system":
            raise ContractError(
                400, "invalid_messages", "system задаёт сервер: клиентские роли только user и assistant"
            )
        if role not in config.CLIENT_ROLES:
            raise ContractError(
                400, "invalid_messages", f'messages[{index}].role "{role}" не поддерживается'
            )
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ContractError(
                400, "invalid_messages", f"messages[{index}].content должен быть непустой строкой"
            )
        messages.append({"role": role, "content": content})
    return messages, max_tokens


def create_app(keys=None, backend=None, access_log=None, rate_limiter=None, queue=None):
    keys = config.load_keys() if keys is None else keys
    backend = backend or Backend(
        config.BACKEND_URL,
        config.MODEL_ALIAS,
        api_key=config.model_api_key(),
        connect_timeout=config.CONNECT_TIMEOUT_SEC,
        generation_timeout=config.GENERATION_TIMEOUT_SEC,
    )
    access_log = access_log or AccessLog(config.ACCESS_LOG_DEFAULT)
    rate_limiter = rate_limiter or SlidingWindowLimiter(
        config.RATE_LIMIT_REQUESTS, config.RATE_LIMIT_WINDOW_SEC
    )
    queue = queue or GenerationQueue(config.MAX_WAITING_REQUESTS, config.QUEUE_WAIT_TIMEOUT_SEC)

    def log(record, status, request_id, label=None, started=None, **extra):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "request_id": request_id,
            "method": record.get("method"),
            "path": record.get("path"),
            "status": status,
            "key_label": label,
        }
        if started is not None:
            entry["total_ms"] = round((time.perf_counter() - started) * 1000)
        entry.update(extra)
        access_log.write(entry)

    async def health(request):
        request_id = new_request_id()
        started = time.perf_counter()
        if not await backend.health():
            log(request, 503, request_id, started=started, error_code="backend_unavailable")
            return error_response(
                503,
                "backend_unavailable",
                f"backend {config.BACKEND_URL} недоступен",
                request_id,
                retry_after=5,
            )
        log(request, 200, request_id, started=started)
        return JSONResponse(
            {
                "status": "ok",
                "backend": "ok",
                "model": config.MODEL_ALIAS,
                "context_window": config.CONTEXT_WINDOW,
                "queue": queue.stats(),
            },
            headers={"x-request-id": request_id},
        )

    async def limits(request):
        request_id = new_request_id()
        return JSONResponse(
            {
                "model": config.MODEL_ALIAS,
                "context_window": config.CONTEXT_WINDOW,
                "max_tokens": {"min": config.MIN_MAX_TOKENS, "max": config.MAX_MAX_TOKENS, "default": config.DEFAULT_MAX_TOKENS},
                "context_margin_tokens": config.CONTEXT_MARGIN_TOKENS,
                "max_body_bytes": config.MAX_BODY_BYTES,
                "rate_limit": {"requests": config.RATE_LIMIT_REQUESTS, "window_sec": config.RATE_LIMIT_WINDOW_SEC},
                "queue": {"active": 1, "waiting": config.MAX_WAITING_REQUESTS, "wait_timeout_sec": config.QUEUE_WAIT_TIMEOUT_SEC},
            },
            headers={"x-request-id": request_id},
        )

    async def models(request):
        request_id = new_request_id()
        label, problem = authorize(request, keys)
        if label is None:
            log(request, 401, request_id, error_code="unauthorized")
            return error_response(401, "unauthorized", problem, request_id)
        log(request, 200, request_id, label=label)
        return JSONResponse(
            {
                "object": "list",
                "data": [
                    {
                        "id": config.MODEL_ALIAS,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "local-home-server",
                    }
                ],
            },
            headers={"x-request-id": request_id},
        )

    async def chat(request):
        request_id = new_request_id()
        started = time.perf_counter()
        label = None
        queue_ms = None
        generation_ms = None
        prompt_tokens = None
        try:
            label, problem = authorize(request, keys)
            if label is None:
                log(request, 401, request_id, error_code="unauthorized")
                return error_response(401, "unauthorized", problem, request_id)

            body = await read_body(request, config.MAX_BODY_BYTES)
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                log(request, 400, request_id, label=label, error_code="invalid_json")
                return error_response(400, "invalid_json", "тело запроса не является JSON", request_id)

            messages, max_tokens = validate_chat_request(payload)

            allowed, retry_after = rate_limiter.check(label)
            if not allowed:
                log(request, 429, request_id, label=label, error_code="rate_limited")
                return error_response(
                    429,
                    "rate_limited",
                    f"лимит {config.RATE_LIMIT_REQUESTS} POST запросов за "
                    f"{config.RATE_LIMIT_WINDOW_SEC:.0f} с для этого ключа исчерпан",
                    request_id,
                    retry_after=retry_after,
                )

            prompt_tokens = await backend.count_prompt_tokens(messages)
            required = prompt_tokens + max_tokens + config.CONTEXT_MARGIN_TOKENS
            if required > config.CONTEXT_WINDOW:
                log(
                    request,
                    400,
                    request_id,
                    label=label,
                    error_code="context_limit",
                    prompt_tokens=prompt_tokens,
                    max_tokens=max_tokens,
                )
                return error_response(
                    400,
                    "context_limit",
                    f"prompt {prompt_tokens} + max_tokens {max_tokens} + запас "
                    f"{config.CONTEXT_MARGIN_TOKENS} = {required} > {config.CONTEXT_WINDOW}; "
                    "историю нужно сократить на клиенте",
                    request_id,
                )

            try:
                waited = await queue.acquire()
            except QueueFullError as exc:
                log(request, 503, request_id, label=label, error_code="queue_full")
                return error_response(
                    503,
                    "queue_full",
                    f"{exc}; занято генерацией и {config.MAX_WAITING_REQUESTS} местами ожидания",
                    request_id,
                    retry_after=5,
                )
            except QueueTimeoutError as exc:
                log(request, 503, request_id, label=label, error_code="queue_timeout")
                return error_response(
                    503,
                    "queue_timeout",
                    f"{exc}; попробуйте позже",
                    request_id,
                    retry_after=10,
                )
            queue_ms = round(waited * 1000)
            try:
                generation_started = time.perf_counter()
                result = await backend.chat(messages, max_tokens)
                generation_ms = round((time.perf_counter() - generation_started) * 1000)
            finally:
                queue.release()

            result = dict(result)
            result["request_id"] = request_id
            result["model"] = config.MODEL_ALIAS
            usage = result.get("usage") or {}
            choice = (result.get("choices") or [{}])[0]
            log(
                request,
                200,
                request_id,
                label=label,
                started=started,
                queue_ms=queue_ms,
                generation_ms=generation_ms,
                prompt_tokens=usage.get("prompt_tokens", prompt_tokens),
                completion_tokens=usage.get("completion_tokens"),
                finish_reason=choice.get("finish_reason"),
            )
            return JSONResponse(result, headers={"x-request-id": request_id})
        except ContractError as exc:
            log(
                request,
                exc.status,
                request_id,
                label=label,
                started=started,
                error_code=exc.code,
                prompt_tokens=prompt_tokens,
            )
            return error_response(exc.status, exc.code, exc.message, request_id)
        except BackendUnavailable as exc:
            log(request, 503, request_id, label=label, error_code="backend_unavailable")
            return error_response(
                503,
                "backend_unavailable",
                f"backend {config.BACKEND_URL} недоступен: {exc}",
                request_id,
                retry_after=5,
            )
        except BackendTimeout as exc:
            log(request, 504, request_id, label=label, error_code="backend_timeout")
            return error_response(
                504, "backend_timeout", f"backend не ответил за {config.GENERATION_TIMEOUT_SEC:.0f} с", request_id
            )
        except BackendStatusError as exc:
            log(request, 502, request_id, label=label, error_code="backend_error")
            return error_response(
                502, "backend_error", f"backend вернул {exc.status_code}: {exc.detail}", request_id
            )
        except Exception as exc:  # no traceback leaves the process
            log(request, 500, request_id, label=label, error_code="internal_error")
            return error_response(500, "internal_error", type(exc).__name__, request_id)

    async def index(request):
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")

    async def root_health(request):
        return PlainTextResponse("day30 private llm service; see /health\n")

    routes = [
        Route("/", index),
        Route("/health", health),
        Route("/limits", limits),
        Route("/v1/models", models),
        Route("/v1/chat/completions", chat, methods=["POST"]),
        Route("/favicon.ico", root_health),
    ]
    app = Starlette(routes=routes)
    app.state.backend = backend
    app.state.queue = queue
    app.state.rate_limiter = rate_limiter
    app.state.keys = keys
    app.state.access_log = access_log
    return app


def build_app():
    """Entry point for uvicorn: fail loudly when keys are missing."""
    if os.environ.get("SERVICE_HOST"):
        config.SERVICE_HOST = os.environ["SERVICE_HOST"]
    return create_app()
