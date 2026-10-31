"""Cloudflare Workers AI image client (FLUX.1 schnell by default).

Workers AI gives every account 10,000 free neurons per day (roughly 170
FLUX.1-schnell images at 1024px / 4 steps, reset daily). It is used as the
fallback provider for the prompt-repair pass when Pollinations is throttled or
returns an error.

The endpoint returns a base64-encoded JPEG inside ``result.image``; bytes are
cached on disk by a content hash of the request, mirroring the Pollinations
client.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from src.errors import ProviderError
from src.http_client import HttpClient

__all__ = ["CloudflareImageClient"]

DEFAULT_MODEL = "@cf/black-forest-labs/flux-1-schnell"


class CloudflareImageClient:
    """Free-tier FLUX image generation through Cloudflare Workers AI."""

    BASE = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"

    def __init__(
        self,
        http: HttpClient,
        cache_dir: Path,
        *,
        account_id: str,
        token: str,
        model: str | None = None,
        steps: int = 4,
    ) -> None:
        if not account_id or not token:
            raise ProviderError("cloudflare image client requires account id and token")
        self._http = http
        self._cache_dir = Path(cache_dir)
        self._account_id = account_id
        self._token = token
        self._model = model or os.environ.get("CLOUDFLARE_IMAGE_MODEL") or DEFAULT_MODEL
        self._steps = max(1, min(int(steps), 8))

    def _cache_key(self, prompt: str, *, seed: int | None) -> str:
        canonical = f"cloudflare|{self._model}|{self._steps}|{seed}|{prompt}"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def generate(
        self,
        prompt: str,
        *,
        width: int = 1280,
        height: int = 720,
        seed: int | None = None,
    ) -> Path:
        """Generate one image and return the cached file path.

        ``width``/``height`` are accepted for interface parity with the other
        image clients but are not sent: FLUX.1 schnell on Workers AI returns a
        square image, which the motion/assembly stages letterbox.
        """
        cache_path = self._cache_dir / f"{self._cache_key(prompt, seed=seed)}.jpg"
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return cache_path

        body: dict[str, object] = {"prompt": prompt, "steps": self._steps}
        if seed is not None:
            body["seed"] = seed

        url = self.BASE.format(account_id=self._account_id, model=self._model)
        try:
            payload = self._http.post_json(
                url,
                json_body=body,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize transport failures
            raise ProviderError(f"cloudflare image request failed: {exc}") from exc

        image = self._extract_image(payload)
        try:
            data = base64.b64decode(image)
        except (ValueError, TypeError) as exc:
            raise ProviderError("cloudflare returned invalid base64 image data") from exc
        if not data:
            raise ProviderError("cloudflare returned an empty image body")

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)
        return cache_path

    @staticmethod
    def _extract_image(payload: object) -> str:
        """Pull ``result.image`` out of the Workers AI response envelope."""
        if not isinstance(payload, dict):
            raise ProviderError(f"cloudflare returned an unexpected response: {payload!r}")
        if payload.get("success") is False:
            errors = payload.get("errors") or payload
            raise ProviderError(f"cloudflare image failed: {errors}")
        result = payload.get("result", payload)
        image = result.get("image") if isinstance(result, dict) else None
        if not isinstance(image, str) or not image:
            raise ProviderError(f"cloudflare response has no image: {payload}")
        return image
