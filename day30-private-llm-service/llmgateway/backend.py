"""HTTP client for the loopback llama-server backend.

Only the endpoints the gateway needs are exposed; llama.cpp endpoints are never
proxied through to clients (see README).
"""
from __future__ import annotations

import httpx


class BackendUnavailable(Exception):
    """Connection to llama-server failed (process down, port closed)."""


class BackendTimeout(Exception):
    """llama-server accepted the connection but did not answer in time."""


class BackendStatusError(Exception):
    """llama-server answered, but not with the expected payload."""

    def __init__(self, status_code, detail=""):
        super().__init__(f"backend status {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class Backend:
    def __init__(self, base_url, model_alias, api_key="", connect_timeout=5.0, generation_timeout=120.0,
                 client=None):
        self.base_url = base_url.rstrip("/")
        self.model_alias = model_alias
        # llama-server --api-key: the gateway is the only holder of this key.
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(generation_timeout, connect=connect_timeout),
        )

    async def aclose(self):
        await self._client.aclose()

    # --- transport ----------------------------------------------------------
    async def _request(self, method, path, **kwargs):
        headers = {**self.headers, **(kwargs.pop("headers", None) or {})}
        try:
            return await self._client.request(method, path, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise BackendTimeout(str(exc) or exc.__class__.__name__) from exc
        except httpx.HTTPError as exc:
            raise BackendUnavailable(str(exc) or exc.__class__.__name__) from exc

    async def _json(self, method, path, **kwargs):
        response = await self._request(method, path, **kwargs)
        if response.status_code != 200:
            raise BackendStatusError(response.status_code, response.text[:200])
        try:
            return response.json()
        except ValueError as exc:
            raise BackendStatusError(response.status_code, "response is not JSON") from exc

    # --- operations ---------------------------------------------------------
    async def health(self):
        """True when the backend answers /health with status ok."""
        try:
            response = await self._request("GET", "/health")
        except (BackendUnavailable, BackendTimeout):
            return False
        if response.status_code != 200:
            return False
        try:
            return response.json().get("status") == "ok"
        except ValueError:
            return False

    async def props(self):
        return await self._json("GET", "/props")

    async def count_prompt_tokens(self, messages):
        """Exact token count of the rendered chat prompt, backend tokenizer.

        /apply-template renders the model's real chat template (system message,
        role markers); /tokenize then counts with the model tokenizer. Verified
        equal to usage.prompt_tokens returned by a real completion request.
        """
        rendered = await self._json("POST", "/apply-template", json={"messages": messages})
        prompt = rendered.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise BackendStatusError(200, "/apply-template returned no prompt")
        tokenized = await self._json("POST", "/tokenize", json={"content": prompt})
        tokens = tokenized.get("tokens")
        if not isinstance(tokens, list):
            raise BackendStatusError(200, "/tokenize returned no token list")
        return len(tokens)

    async def chat(self, messages, max_tokens):
        """Run one generation. Sampling is pinned: temperature 0, no streaming."""
        payload = {
            "model": self.model_alias,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
        }
        return await self._json("POST", "/v1/chat/completions", json=payload)
