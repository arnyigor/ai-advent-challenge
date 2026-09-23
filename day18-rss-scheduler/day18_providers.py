"""Free-only provider chain for a short RSS digest."""

import os
import requests

GEMINI_MODELS = ("gemini-3.7-flash", "gemini-3.5-flash", "gemini-2.5-flash")
OPENROUTER_MODEL = "qwen/qwen3.8-27b:free"
WORMSOFT_MODEL = "qwen/qwen3.8:27b"
WORMSOFT_URL = "https://ai.wormsoft.ru/api/gpt"


def _post(url, key, payload, *, gemini=False, timeout=60):
    headers = {"Content-Type": "application/json"}
    headers["x-goog-api-key" if gemini else "Authorization"] = key if gemini else f"Bearer {key}"
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def generate(provider, prompt):
    if provider in GEMINI_MODELS:
        key = os.environ["GEMINI_API_KEY"]
        data = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{provider}:generateContent", key, {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 2800, "thinkingConfig": {"thinkingLevel": "low"}}}, gemini=True)
        return "".join(part.get("text", "") for part in data["candidates"][0]["content"]["parts"]), provider
    if provider == "openrouter":
        key = os.environ["OPENROUTER_API_KEY"]
        data = _post("https://openrouter.ai/api/v1/chat/completions", key, {"model": OPENROUTER_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 2000})
        model = data.get("model", OPENROUTER_MODEL)
        return data["choices"][0]["message"]["content"], model
    if provider == "wormsoft":
        key = os.environ["WORMSOFT_API_KEY"]
        base = (os.environ.get("WORMSOFT_BASE_URL") or WORMSOFT_URL).rstrip("/")
        data = _post(f"{base}/chat/completions", key, {"model": WORMSOFT_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 2000}, timeout=150)
        return data["choices"][0]["message"]["content"], WORMSOFT_MODEL
    raise ValueError("Unknown provider")


def fallback(prompt, *, call=generate):
    attempts = []
    for provider, env_name in ((GEMINI_MODELS[0], "GEMINI_API_KEY"), (GEMINI_MODELS[1], "GEMINI_API_KEY"), ("openrouter", "OPENROUTER_API_KEY"), ("wormsoft", "WORMSOFT_API_KEY"), (GEMINI_MODELS[2], "GEMINI_API_KEY")):
        if not os.environ.get(env_name):
            attempts.append({"provider": provider, "result": "missing_key"})
            continue
        try:
            body, model = call(provider, prompt)
            if not isinstance(body, str) or len(body.strip()) < 500:
                raise ValueError("response too short")
            attempts.append({"provider": provider, "result": "ok"})
            return {"body": body.strip(), "provider": provider, "model": model, "attempts": attempts}
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            attempts.append({"provider": provider, "result": "failed", "error": f"HTTP {code}" if code else type(exc).__name__})
    return {"body": None, "provider": None, "model": None, "attempts": attempts}
