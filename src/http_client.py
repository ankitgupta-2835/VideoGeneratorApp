"""HTTP client with retries, backoff, and an optional on-disk cache.

Wraps ``httpx`` so every provider call gets consistent retry/backoff behavior
and can be cached to avoid burning free-tier quotas. Network/HTTP failures are
raised as :class:`ProviderError`.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from src.errors import ProviderError

__all__ = ["HttpClient"]

_RETRY_STATUS = {429, 500, 502, 503, 504}

#: Per-request timeout (seconds). LLM providers (notably Gemini flash with
#: thinking enabled) can take well over 30s for a long JSON prompt, so the
#: default is generous and can be tuned with ``HTTP_TIMEOUT``.
DEFAULT_TIMEOUT = 90.0


def _default_timeout() -> float:
    raw = os.environ.get("HTTP_TIMEOUT", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_TIMEOUT


def _error_detail(resp: httpx.Response) -> str:
    """Return a short one-line summary of a provider's error body.

    Providers put the actionable part (e.g. "model ... is not found for API
    version v1beta") in the body, not the status line, so include it when it
    is available and readable.
    """
    try:
        data = resp.json()
    except ValueError:
        text = resp.text.strip()
        # HTML error pages (e.g. Reddit's 403) add noise, not information.
        if not text or text.startswith("<"):
            return ""
        return f": {text[:300]}"
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            return f": {str(error['message'])[:300]}"
        if isinstance(error, str):
            return f": {error[:300]}"
    text = resp.text.strip()
    return f": {text[:300]}" if text else ""


class HttpClient:
    def __init__(
        self,
        *,
        timeout: float | None = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        cache_dir: str | Path | None = None,
        client: httpx.Client | None = None,
        headers: dict[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout is None:
            timeout = _default_timeout()
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._sleep = sleep
        self._client = client or httpx.Client(timeout=timeout, headers=headers or {})
        self._owns_client = client is None

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _cache_path(self, kind: str, key: str) -> Path | None:
        if self.cache_dir is None:
            return None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self.cache_dir / f"{kind}_{digest}"

    def _backoff(self, attempt: int, resp: httpx.Response) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        delay = self.backoff_base * (2**attempt)
        if resp.status_code == 503:
            # "High demand" spikes last seconds-to-minutes; a sub-second retry
            # just burns the attempt budget.
            delay = max(delay, 5.0)
        return delay

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.request(
                    method, url, params=params, json=json_body, headers=headers
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    self._sleep(self.backoff_base * (2**attempt))
                    continue
                break

            if resp.status_code < 400:
                return resp
            if resp.status_code in _RETRY_STATUS and attempt < self.max_retries:
                self._sleep(self._backoff(attempt, resp))
                continue
            raise ProviderError(f"{method} {url} -> HTTP {resp.status_code}{_error_detail(resp)}")

        raise ProviderError(
            f"{method} {url} failed after {self.max_retries + 1} attempts: {last_exc}"
        )

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
    ) -> Any:
        path = self._cache_path("json", f"GET:{url}:{params}")
        if use_cache and path is not None and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        resp = self._request("GET", url, params=params, headers=headers)
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(f"invalid JSON from {url}") from exc
        if path is not None:
            path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def get_bytes(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
    ) -> bytes:
        path = self._cache_path("bin", f"GETB:{url}:{params}")
        if use_cache and path is not None and path.exists():
            return path.read_bytes()
        resp = self._request("GET", url, params=params, headers=headers)
        data = resp.content
        if path is not None:
            path.write_bytes(data)
        return data

    def post_json(
        self,
        url: str,
        *,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        resp = self._request("POST", url, json_body=json_body, headers=headers)
        try:
            return resp.json()
        except ValueError as exc:
            raise ProviderError(f"invalid JSON from {url}") from exc

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
