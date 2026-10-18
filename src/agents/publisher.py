"""``publisher`` agent: manual-by-default publish, with optional upload.

The publisher is deliberately *manual by default*. It always fires a
``publish`` checkpoint alert (so a human knows a finished video is waiting),
records that alert and the run status in the store when one is supplied, and
only performs an actual upload when an :class:`Uploader` is configured **and**
``dry_run`` is ``False``.

Idempotency: if the store already reports the run as ``published`` the agent
short-circuits to ``skipped`` and never uploads again.

Failure policy
--------------
An upload failure is surfaced two ways: the typed :class:`PublishResult` has a
``failed`` status, and the agent returns an ``AgentResult`` with
``status="fail"`` carrying the error in ``notes``. We prefer the ``fail``
result because the pipeline should treat "we tried to publish and could not"
as a real failure (retryable / visible), not as a successful no-op; callers
that want the structured reason read it from the notes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from src.agents.base import Agent, AgentResult
from src.agents.seo import PublishMetadata
from src.errors import ProviderError
from src.notify import Notifier, checkpoint_text
from src.secrets import Secrets
from src.store.db import Database

__all__ = [
    "PublishInput",
    "PublishResult",
    "PublisherAgent",
    "Uploader",
    "YouTubeUploader",
]

#: Checkpoint name used for the "ready to publish" alert.
PUBLISH_CHECKPOINT = "publish"


class PublishInput(BaseModel):
    """Input contract for the ``publisher`` agent."""

    run_id: str
    language: str = "en"
    metadata: PublishMetadata
    video_path: Path
    short_path: Path | None = None
    dry_run: bool = True  # default: manual publish (no upload)


class PublishResult(BaseModel):
    """Output contract: what the publisher did (or declined to do)."""

    status: str  # "ready" | "published" | "skipped" | "failed"
    platform: str = "youtube"
    url: str | None = None
    alerts_sent: list[str] = Field(default_factory=list)


@runtime_checkable
class Uploader(Protocol):
    """A thing that can upload a finished video and return its URL."""

    def upload(
        self, video_path: Path, metadata: PublishMetadata, *, language: str = "en"
    ) -> str: ...


class YouTubeUploader:
    """Real YouTube uploader (thin placeholder until OAuth is wired up).

    The Google API client is imported lazily so the package stays importable
    without the optional dependency, and a
    :class:`~src.errors.ProviderError` is raised when credentials for the
    requested language are missing or the dependency is unavailable.
    """

    def __init__(self, secrets: Secrets) -> None:
        self._secrets = secrets

    def upload(
        self, video_path: Path, metadata: PublishMetadata, *, language: str = "en"
    ) -> str:  # noqa: ARG002 - signature matches the Uploader protocol
        credential = (
            self._secrets.youtube_client_secret_hi
            if language.lower().startswith("hi")
            else self._secrets.youtube_client_secret_en
        )
        if credential is None:
            raise ProviderError(f"no YouTube credentials configured for language {language!r}")
        try:  # pragma: no cover - optional dependency, exercised only for real uploads
            from googleapiclient.discovery import build  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("google-api-python-client is not installed") from exc
        raise ProviderError("YouTube upload is not yet implemented")


class PublisherAgent(Agent):
    """Manual-by-default publisher with optional, opt-in upload."""

    name = "publisher"
    input_model = PublishInput
    output_model = PublishResult

    def __init__(
        self,
        notifier: Notifier,
        uploader: Uploader | None = None,
        store: Database | None = None,
    ) -> None:
        self._notifier = notifier
        self._uploader = uploader
        self._store = store

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _ready_message(self, payload: PublishInput) -> str:
        return f"Ready to publish: {payload.metadata.title}"

    def _send_ready(self, payload: PublishInput) -> tuple[list[str], list[str]]:
        """Fire the ready-to-publish alert.

        Returns the list of checkpoints sent and any notes. A notifier failure
        is caught (never fails the run) and returned as a note.
        """
        text = checkpoint_text(
            PUBLISH_CHECKPOINT, self._ready_message(payload), run_id=payload.run_id
        )
        try:
            self._notifier.send(text)
        except Exception as exc:  # a broken notifier must not fail publishing
            return [], [f"notifier failed: {exc}"]
        return [PUBLISH_CHECKPOINT], []

    def _persist(self, payload: PublishInput, result: PublishResult) -> None:
        """Record the alert and run status when a store is configured."""
        if self._store is None:
            return
        if PUBLISH_CHECKPOINT in result.alerts_sent:
            self._store.record_alert(
                PUBLISH_CHECKPOINT, self._ready_message(payload), run_id=payload.run_id
            )
        self._store.set_run_status(payload.run_id, result.status)

    def _already_published(self, run_id: str) -> bool:
        if self._store is None:
            return False
        run = self._store.get_run(run_id)
        return run is not None and run.get("status") == "published"

    # ------------------------------------------------------------------ #
    # work
    # ------------------------------------------------------------------ #
    def _run(self, payload: PublishInput) -> AgentResult:
        # Idempotent: never publish the same run twice.
        if self._already_published(payload.run_id):
            result = PublishResult(status="skipped")
            return AgentResult(status="ok", data=result, notes=["run already published"])

        alerts_sent, notes = self._send_ready(payload)

        if payload.dry_run or self._uploader is None:
            result = PublishResult(status="ready", alerts_sent=alerts_sent)
            self._persist(payload, result)
            reason = "dry run" if payload.dry_run else "no uploader configured"
            return AgentResult(
                status="ok",
                data=result,
                notes=[*notes, f"manual publish ({reason})"],
            )

        try:
            url = self._uploader.upload(
                payload.video_path, payload.metadata, language=payload.language
            )
        except Exception as exc:  # upload failure is a real failure
            failed = PublishResult(status="failed", alerts_sent=alerts_sent)
            self._persist(payload, failed)
            return AgentResult(status="fail", notes=[*notes, f"upload failed: {exc}"])

        result = PublishResult(status="published", url=url, alerts_sent=alerts_sent)
        self._persist(payload, result)
        return AgentResult(
            status="ok",
            data=result,
            notes=[*notes, f"published at {url}"],
        )
