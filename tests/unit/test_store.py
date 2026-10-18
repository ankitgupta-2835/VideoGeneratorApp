"""Task 0.6 tests: SQLite store CRUD, dedup, migrations, constraints."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.errors import StoreError
from src.store.db import Database


@pytest.fixture()
def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    database.migrate()
    yield database
    database.close()


def test_migrate_is_idempotent(tmp_path: Path):
    database = Database(tmp_path / "t.db")
    database.migrate()
    database.migrate()  # no error
    assert set(database.tables()) >= {"alerts", "attempts", "runs", "topics"}
    database.close()


def test_add_and_detect_seen_topic(db: Database):
    assert db.add_topic("ai_tech", "New model released", score=5.0) is True
    assert db.topic_seen("ai_tech", "New model released") is True
    assert db.topic_seen("finance", "New model released") is False


def test_duplicate_topic_is_ignored(db: Database):
    assert db.add_topic("ai_tech", "Same title") is True
    assert db.add_topic("ai_tech", "Same title") is False
    assert len(db.topics_for_category("ai_tech")) == 1


def test_topics_ordered_by_score(db: Database):
    db.add_topic("ai_tech", "low", score=1.0)
    db.add_topic("ai_tech", "high", score=9.0)
    db.add_topic("ai_tech", "mid", score=5.0)
    titles = [t["title"] for t in db.topics_for_category("ai_tech")]
    assert titles == ["high", "mid", "low"]


def test_run_lifecycle(db: Database):
    db.create_run("run-1", "ai_tech", "en")
    db.set_run_status("run-1", "generating")
    db.set_run_topic("run-1", "Top story")
    db.set_run_quality("run-1", 0.82)
    run = db.get_run("run-1")
    assert run is not None
    assert run["status"] == "generating"
    assert run["chosen_topic"] == "Top story"
    assert run["quality_score"] == pytest.approx(0.82)
    assert db.get_run("missing") is None


def test_attempt_numbering(db: Database):
    db.create_run("run-1", "ai_tech", "en")
    assert db.add_attempt("run-1", "full", reason="first") == 1
    assert db.add_attempt("run-1", "scenes", reason="fix scene 3") == 2
    assert db.add_attempt("run-1", "assets") == 3
    attempts = db.attempts_for_run("run-1")
    assert [a["attempt_no"] for a in attempts] == [1, 2, 3]
    assert attempts[1]["reason"] == "fix scene 3"


def test_attempt_requires_existing_run(db: Database):
    with pytest.raises(StoreError):
        db.add_attempt("ghost-run", "full")


def test_alerts_recorded_and_listed(db: Database):
    db.create_run("run-1", "ai_tech", "en")
    db.record_alert("topic", "Chose: Top story", run_id="run-1")
    db.record_alert("video_ready", "Preview at /output/run-1", run_id="run-1")
    alerts = db.alerts_for_run("run-1")
    assert [a["checkpoint"] for a in alerts] == ["topic", "video_ready"]
