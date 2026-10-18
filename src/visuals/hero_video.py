"""Hero-video client with an ordered provider cascade and image fallback.

A "hero" video is the short, high-attention text-to-video clip that opens a
piece of content. This module keeps that step deliberately resilient:

- Providers are tried in order. Any provider may fail for any reason; failures
  are recorded and the cascade moves on.
- The first provider to return a file wins and the result is reported as
  ``kind="hero"``.
- If **every** provider fails, the client degrades gracefully to a generated
  still image (Pollinations) so the pipeline always produces something usable;
  that result is reported as ``kind="image"``.

Provider calls are wrapped behind :class:`HeroProvider`, a small runtime
checkable protocol, so new backends can be added without touching the cascade.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from src.errors import ProviderError
from src.http_client import HttpClient
from src.secrets import Secrets
from src.visuals.images_pollinations import PollinationsImageClient

__all__ = [
    "HeroProvider",
    "HeroResult",
    "HeroVideoClient",
    "LumaProvider",
    "build_providers",
]


class HeroResult(BaseModel):
    """Outcome of a hero-asset request."""

    path: str
    kind: Literal["hero", "image"]
    provider: str


@runtime_checkable
class HeroProvider(Protocol):
    """Interface every hero-video backend implements."""

    name: str

    def generate(self, prompt: str, *, duration_sec: float, out_dir: Path) -> Path:
        """Generate a short video for ``prompt`` under ``out_dir`` and return it."""
        ...


class LumaProvider:
    """Real backend for the Luma Dream Machine text-to-video API.

    The flow is the usual asynchronous one: create a generation, poll it until
    it reports ``completed``, then download the produced mp4. Both the poll
    interval and the sleep function are injectable so tests run without delay.
    """

    name = "luma"
    BASE = "https://api.lumalabs.ai/dream-machine/v1"

    def __init__(
        self,
        http: HttpClient,
        api_key: str,
        *,
        poll_interval: float = 2.0,
        max_polls: int = 60,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http
        self._api_key = api_key
        self._poll_interval = poll_interval
        self._max_polls = max_polls
        self._sleep = sleep

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def generate(self, prompt: str, *, duration_sec: float, out_dir: Path) -> Path:
        created = self._http.post_json(
            f"{self.BASE}/generations",
            json_body={"prompt": prompt, "duration": duration_sec},
            headers=self._headers,
        )
        generation_id = _extract(created, "id")
        if not generation_id:
            raise ProviderError("luma create response missing generation id")

        for _ in range(self._max_polls):
            state = self._http.get_json(
                f"{self.BASE}/generations/{generation_id}", headers=self._headers
            )
            status = _extract(state, "state")
            if status == "completed":
                video_url = _extract(state, "assets", "video")
                if not video_url:
                    raise ProviderError("luma completed generation has no video asset")
                data = self._http.get_bytes(video_url, headers=self._headers)
                if not data:
                    raise ProviderError("luma returned an empty video body")
                out_dir.mkdir(parents=True, exist_ok=True)
                path = out_dir / f"{generation_id}.mp4"
                path.write_bytes(data)
                return path
            if status in {"failed", "error"}:
                raise ProviderError(f"luma generation {generation_id} failed")
            self._sleep(self._poll_interval)

        raise ProviderError(f"luma generation {generation_id} timed out")


def _extract(data: Any, *keys: str) -> Any:
    """Walk nested dicts, returning ``None`` on any missing/mismatched level."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


class HeroVideoClient:
    """Try hero providers in order, degrading to a generated still image."""

    def __init__(self, providers: list[HeroProvider], fallback: PollinationsImageClient) -> None:
        self._providers = providers
        self._fallback = fallback
        #: Notes from the most recent :meth:`generate` call (for observability).
        self.last_notes: list[str] = []

    def generate(
        self,
        prompt: str,
        *,
        duration_sec: float = 5.0,
        out_dir: Path,
        width: int = 1280,
        height: int = 720,
    ) -> HeroResult:
        notes: list[str] = []
        for provider in self._providers:
            try:
                path = provider.generate(prompt, duration_sec=duration_sec, out_dir=out_dir)
            except Exception as exc:  # noqa: BLE001 - any provider failure just moves on
                notes.append(f"{provider.name}: {exc}")
                continue
            self.last_notes = notes
            return HeroResult(path=str(path), kind="hero", provider=provider.name)

        self.last_notes = notes
        path = self._fallback.generate(prompt, width=width, height=height)
        return HeroResult(path=str(path), kind="image", provider="pollinations")


def build_providers(secrets: Secrets, *, http: HttpClient | None = None) -> list[HeroProvider]:
    """Return hero providers whose API keys are configured.

    ``Secrets`` currently has no dedicated hero-video key, so this returns an
    empty list; the lookup is written defensively so adding a ``luma_api_key``
    field later lights the provider up automatically.
    """
    owners: list[tuple[str, str]] = [("luma", "luma_api_key")]
    providers: list[HeroProvider] = []
    for name, field in owners:
        key = getattr(secrets, field, None)
        if key is None:
            continue
        value = key.get_secret_value() if hasattr(key, "get_secret_value") else str(key)
        if not value:
            continue
        if name == "luma":
            providers.append(LumaProvider(http or HttpClient(), value))
    return providers
