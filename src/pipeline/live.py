"""Live wiring for the pipeline CLI (task 5.9).

:func:`build_live_stages` assembles the *real* dependencies (LLM client, HTTP
client, notifier, SQLite store, TTS backend, image/stock/hero clients) from the
loaded :class:`~src.secrets.Secrets` and :class:`~src.config.Settings`, then
hands them to :func:`~src.pipeline.stages.build_pipeline`.

Construction is side-effect free from a network standpoint: the HTTP client,
Pollinations/stock/hero clients and the TTS backend only touch the network when
a stage actually runs. The one thing this module *does* do eagerly is open the
SQLite store and create its schema (local disk only).

``demo=True`` implements the bounded demo runner contract:

* **image-only visuals** — no hero providers and no stock providers are wired,
  so every scene degrades to a generated still;
* **dry-run publish** — the publisher never uploads (``dry_run=True``);
* the blueprint is capped to ``max_scenes`` by the SCRIPT stage.

The language (``en`` for demos) is chosen by the CLI, which owns the
orchestrator run; it is not part of this builder's inputs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.audio.tts import EdgeTTSBackend, TTSBackend
from src.config import Settings
from src.errors import ProviderError
from src.http_client import HttpClient
from src.llm.client import LLMClient, build_llm_client
from src.notify import Notifier, build_notifier
from src.pipeline.orchestrator import StageFn
from src.pipeline.stages import build_pipeline
from src.rerun.controller import Stage
from src.secrets import Secrets
from src.store.db import Database
from src.visuals.hero_video import HeroVideoClient, build_providers
from src.visuals.images_pollinations import PollinationsImageClient
from src.visuals.stock import PexelsClient, PixabayClient

__all__ = ["build_live_stages"]

#: LLM provider -> the secret field (and thus env var) that must be set.
_PROVIDER_KEY_FIELD: dict[str, str] = {
    "gemini": "gemini_api_key",
    "groq": "groq_api_key",
    "openrouter": "openrouter_api_key",
}


def _require_llm_key(secrets: Secrets) -> None:
    """Raise a clear :class:`ProviderError` when the selected LLM key is absent.

    :func:`~src.secrets.load_secrets` normally guarantees this, but the check
    is repeated here so a hand-built/mock ``Secrets`` still fails with a
    message that names the exact environment variable to set.
    """
    field = _PROVIDER_KEY_FIELD.get(secrets.llm_provider)
    if field is not None and getattr(secrets, field, None) is None:
        raise ProviderError(
            f"missing LLM API key: set {field.upper()} "
            f"(LLM_PROVIDER={secrets.llm_provider}) in the environment or .env"
        )


def _build_llm(secrets: Secrets, *, http: HttpClient, llm: LLMClient | None) -> LLMClient:
    if llm is not None:
        return llm
    _require_llm_key(secrets)
    return build_llm_client(secrets, http=http)


def _build_store(settings: Settings, store: Database | None) -> Database | None:
    if store is not None:
        return store
    database = Database(settings.paths.db_path)
    database.migrate()
    return database


def _build_stock_client(secrets: Secrets, http: HttpClient) -> Any:
    """Return a stock client for whichever provider key is configured (or None)."""
    if secrets.pexels_api_key is not None:
        return PexelsClient(http, secrets.pexels_api_key.get_secret_value())
    if secrets.pixabay_api_key is not None:
        return PixabayClient(http, secrets.pixabay_api_key.get_secret_value())
    return None


def build_live_stages(
    *,
    secrets: Secrets,
    settings: Settings,
    out_dir: Path,
    demo: bool = False,
    max_scenes: int | None = None,
    http: HttpClient | None = None,
    notifier: Notifier | None = None,
    store: Database | None = None,
    llm: LLMClient | None = None,
    tts_backend: TTSBackend | None = None,
    image_client: Any = None,
    hero_client: Any = None,
    stock_client: Any = None,
    **kw: Any,
) -> dict[Stage, StageFn]:
    """Assemble the real dependencies and return the wired stage mapping.

    All dependencies are injectable so tests can bypass the network entirely.
    Building the returned clients performs **no** network I/O; each client only
    reaches the network once its stage runs during the orchestrator run.

    In ``demo=True`` mode the visual tier is constrained to generated stills
    (``hero_client`` and ``stock_client`` are forced to ``None``) and the
    publisher is put in dry-run mode, matching the bounded demo runner
    contract.
    """
    cache_dir = Path(settings.paths.assets_dir) / "cache"
    http = http or HttpClient(cache_dir=cache_dir)

    llm = _build_llm(secrets, http=http, llm=llm)
    notifier = notifier if notifier is not None else build_notifier(secrets, http=http)
    store = _build_store(settings, store)
    tts_backend = tts_backend if tts_backend is not None else EdgeTTSBackend()

    pollinations = (
        image_client
        if isinstance(image_client, PollinationsImageClient)
        else PollinationsImageClient(http, cache_dir / "images")
    )
    if image_client is None:
        image_client = pollinations

    if demo:
        # Image-only: never reach for a hero or stock provider.
        hero_client = None
        stock_client = None
    else:
        if hero_client is None:
            hero_client = HeroVideoClient(
                build_providers(secrets, http=http), fallback=pollinations
            )
        if stock_client is None:
            stock_client = _build_stock_client(secrets, http)

    return build_pipeline(
        llm=llm,
        notifier=notifier,
        store=store,
        tts_backend=tts_backend,
        image_client=image_client,
        hero_client=hero_client,
        stock_client=stock_client,
        http=http,
        out_dir=Path(out_dir),
        max_scenes=max_scenes,
        dry_run=demo,
        **kw,
    )
