"""Task 4.5 tests: publisher agent (manual-by-default + optional upload)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.publisher import (
    PublisherAgent,
    PublishInput,
    PublishResult,
    YouTubeUploader,
)
from src.agents.seo import PublishMetadata
from src.errors import ProviderError
from src.notify import FakeNotifier
from src.secrets import Secrets
from src.store.db import Database


def make_input(tmp_path: Path, **overrides) -> PublishInput:
    metadata = PublishMetadata(
        title="A great video",
        description="desc",
        tags=["ai"],
        thumbnail_prompt="thumb",
    )
    data = {
        "run_id": "run-1",
        "language": "en",
        "metadata": metadata,
        "video_path": tmp_path / "video.mp4",
    }
    data.update(overrides)
    return PublishInput(**data)


class FakeUploader:
    def __init__(self, url: str = "https://youtu.be/abc") -> None:
        self.url = url
        self.calls = 0

    def upload(self, video_path: Path, metadata: PublishMetadata, *, language: str = "en") -> str:
        self.calls += 1
        return self.url


class BoomUploader:
    def upload(self, video_path: Path, metadata: PublishMetadata, *, language: str = "en") -> str:
        raise ProviderError("upload exploded")


class BoomNotifier:
    def send(self, text: str) -> None:
        raise ProviderError("telegram down")


def test_dry_run_is_ready_and_alerts(tmp_path: Path):
    notifier = FakeNotifier()
    agent = PublisherAgent(notifier)

    result = agent.run(make_input(tmp_path, dry_run=True))

    assert result.status == "ok"
    assert isinstance(result.data, PublishResult)
    assert result.data.status == "ready"
    assert result.data.url is None
    assert result.data.alerts_sent == ["publish"]
    assert len(notifier.messages) == 1
    assert notifier.messages[0].startswith("[run-1] PUBLISH:")
    assert "Ready to publish" in notifier.messages[0]


def test_upload_when_not_dry_run(tmp_path: Path):
    notifier = FakeNotifier()
    uploader = FakeUploader()
    agent = PublisherAgent(notifier, uploader=uploader)

    result = agent.run(make_input(tmp_path, dry_run=False))

    assert result.status == "ok"
    assert result.data.status == "published"
    assert result.data.url == "https://youtu.be/abc"
    assert result.data.alerts_sent == ["publish"]
    assert uploader.calls == 1


def test_notifier_failure_does_not_fail_run(tmp_path: Path):
    agent = PublisherAgent(BoomNotifier())

    result = agent.run(make_input(tmp_path, dry_run=True))

    assert result.status == "ok"
    assert result.data.status == "ready"
    assert result.data.alerts_sent == []
    assert any("notifier failed" in note for note in result.notes)


def test_idempotent_skips_already_published(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    db.migrate()
    db.create_run("run-1", "ai_tech", "en")
    db.set_run_status("run-1", "published")
    notifier = FakeNotifier()
    uploader = FakeUploader()
    agent = PublisherAgent(notifier, uploader=uploader, store=db)

    result = agent.run(make_input(tmp_path, dry_run=False))

    assert result.status == "ok"
    assert result.data.status == "skipped"
    assert result.data.url is None
    assert uploader.calls == 0
    assert notifier.messages == []
    db.close()


def test_upload_failure_is_agent_fail(tmp_path: Path):
    notifier = FakeNotifier()
    agent = PublisherAgent(notifier, uploader=BoomUploader())

    result = agent.run(make_input(tmp_path, dry_run=False))

    assert result.status == "fail"
    assert any("upload failed" in note for note in result.notes)
    assert len(notifier.messages) == 1  # the ready alert still went out


def test_store_records_alert_and_status(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    db.migrate()
    db.create_run("run-1", "ai_tech", "en")
    notifier = FakeNotifier()
    agent = PublisherAgent(notifier, store=db)

    result = agent.run(make_input(tmp_path, dry_run=True))

    assert result.data.status == "ready"
    alerts = db.alerts_for_run("run-1")
    assert len(alerts) == 1
    assert alerts[0]["checkpoint"] == "publish"
    assert db.get_run("run-1")["status"] == "ready"
    db.close()


def test_youtube_uploader_without_credentials_raises(tmp_path: Path):
    uploader = YouTubeUploader(Secrets(gemini_api_key="k"))
    with pytest.raises(ProviderError):
        uploader.upload(tmp_path / "video.mp4", PublishMetadata(title="t", description="d"))
