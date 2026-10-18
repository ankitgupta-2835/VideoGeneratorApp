"""Task 0.3 tests: config loading and schema validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from src.config import ConfigError, load_config

REPO_CONFIG = Path(__file__).resolve().parents[2] / "config"

VALID_SETTINGS: dict[str, Any] = {"languages": ["en"]}
VALID_CATEGORIES: dict[str, Any] = {
    "rotation": ["ai_tech"],
    "categories": {
        "ai_tech": {
            "display_name": "AI & Tech",
            "keywords": ["ai"],
            "subreddits": ["technology"],
        }
    },
}
VALID_VOICES: dict[str, Any] = {
    "voices": {"en": {"voice": "en-US-AriaNeural", "language_name": "English", "channel": "@c"}}
}


def write_config(
    base: Path,
    *,
    settings: Any | None = None,
    categories: Any | None = None,
    voices: Any | None = None,
) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    files = {
        "settings.yaml": VALID_SETTINGS if settings is None else settings,
        "categories.yaml": VALID_CATEGORIES if categories is None else categories,
        "voices.yaml": VALID_VOICES if voices is None else voices,
    }
    for name, data in files.items():
        (base / name).write_text(yaml.safe_dump(data), encoding="utf-8")
    return base


def test_load_repo_config_ok():
    cfg = load_config(REPO_CONFIG)
    assert cfg.settings.video.short.max_duration_sec == 180
    assert "ai_tech" in cfg.categories.categories
    assert cfg.settings.languages == ["en", "hi"]
    assert cfg.voices.voices["hi"].language_name == "Hindi"


def test_missing_file_raises(tmp_path: Path):
    (tmp_path / "settings.yaml").write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path)


def test_empty_settings_uses_defaults(tmp_path: Path):
    cfg = load_config(write_config(tmp_path, settings={}))
    # languages defaults to ["en"], which is present in voices
    assert cfg.settings.languages == ["en"]
    assert cfg.settings.publish_mode == "manual"
    assert cfg.settings.video.long.target_duration_sec == 270
    assert cfg.settings.paths.output_dir == Path("data/output")


def test_short_over_limit_raises(tmp_path: Path):
    bad = {"video": {"short": {"max_duration_sec": 200}}}
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, settings=bad))


def test_long_duration_order_raises(tmp_path: Path):
    bad = {"video": {"long": {"min_duration_sec": 300, "target_duration_sec": 200}}}
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, settings=bad))


def test_language_without_voice_raises(tmp_path: Path):
    with pytest.raises(ConfigError, match="without a configured voice"):
        load_config(write_config(tmp_path, settings={"languages": ["en", "hi"]}))


def test_rotation_unknown_category_raises(tmp_path: Path):
    bad = {"rotation": ["nope"], "categories": VALID_CATEGORIES["categories"]}
    with pytest.raises(ConfigError, match="unknown categories"):
        load_config(write_config(tmp_path, categories=bad))


def test_top_level_must_be_mapping(tmp_path: Path):
    with pytest.raises(ConfigError, match="mapping"):
        load_config(write_config(tmp_path, settings=["not", "a", "mapping"]))
