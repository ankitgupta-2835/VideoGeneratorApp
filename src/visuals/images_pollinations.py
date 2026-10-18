"""Pollinations image generation client with a content-hash disk cache.

Given a prompt, requests a generated image from the free Pollinations endpoint
and stores the returned bytes on disk. The cache key is a hash of the request
parameters, so repeat requests for the same prompt/size/seed skip the network
entirely.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import quote

from src.errors import ProviderError
from src.http_client import HttpClient

__all__ = ["PollinationsImageClient"]


class PollinationsImageClient:
    BASE = "https://image.pollinations.ai/prompt"

    def __init__(self, http: HttpClient, cache_dir: Path) -> None:
        self._http = http
        self._cache_dir = Path(cache_dir)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _cache_key(
        self, prompt: str, *, width: int, height: int, seed: int | None, model: str
    ) -> str:
        canonical = f"{model}|{width}x{height}|{seed}|{prompt}"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def generate(
        self,
        prompt: str,
        *,
        width: int = 1280,
        height: int = 720,
        seed: int | None = None,
        model: str = "flux",
    ) -> Path:
        key = self._cache_key(prompt, width=width, height=height, seed=seed, model=model)
        cache_path = self._cache_dir / f"{key}.jpg"

        if cache_path.exists() and cache_path.stat().st_size > 0:
            return cache_path

        url = f"{self.BASE}/{quote(prompt, safe='')}"
        params: dict[str, object] = {
            "width": width,
            "height": height,
            "model": model,
            "nologo": "true",
        }
        if seed is not None:
            params["seed"] = seed

        data = self._http.get_bytes(url, params=params)
        if not data:
            raise ProviderError("pollinations returned an empty image body")

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)
        return cache_path
