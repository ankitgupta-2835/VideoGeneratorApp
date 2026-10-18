"""Configuration loader with schema validation.

Loads and validates the three YAML files under ``config/``:

- ``settings.yaml``   -> :class:`Settings`
- ``categories.yaml`` -> :class:`Categories`
- ``voices.yaml``     -> :class:`Voices`

All configuration problems are raised as :class:`ConfigError` so callers have a
single exception type to handle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from src.errors import ConfigError

__all__ = [
    "Config",
    "ConfigError",
    "Category",
    "Categories",
    "Settings",
    "Voices",
    "load_config",
]


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class Paths(BaseModel):
    output_dir: Path = Path("data/output")
    assets_dir: Path = Path("data/assets")
    db_path: Path = Path("data/history.db")


class LongVideo(BaseModel):
    aspect_ratio: str = "16:9"
    target_duration_sec: int = Field(default=270, gt=0)
    min_duration_sec: int = Field(default=240, gt=0)
    max_duration_sec: int = Field(default=330, gt=0)
    fps: int = Field(default=30, gt=0, le=60)

    @model_validator(mode="after")
    def _duration_ordering(self) -> LongVideo:
        if not (self.min_duration_sec <= self.target_duration_sec <= self.max_duration_sec):
            raise ValueError(
                "long video durations must satisfy min <= target <= max "
                f"(got {self.min_duration_sec} / {self.target_duration_sec} / "
                f"{self.max_duration_sec})"
            )
        return self


class ShortVideo(BaseModel):
    aspect_ratio: str = "9:16"
    max_duration_sec: int = Field(default=180, gt=0)
    fps: int = Field(default=30, gt=0, le=60)

    @field_validator("max_duration_sec")
    @classmethod
    def _shorts_limit(cls, value: int) -> int:
        if value > 180:
            raise ValueError("Short duration cannot exceed 180s (YouTube Shorts hard limit)")
        return value


class Video(BaseModel):
    long: LongVideo = Field(default_factory=LongVideo)
    short: ShortVideo = Field(default_factory=ShortVideo)


class Settings(BaseModel):
    paths: Paths = Field(default_factory=Paths)
    video: Video = Field(default_factory=Video)
    languages: list[str] = Field(default_factory=lambda: ["en"])
    schedule_time: str = "07:00"
    autonomy: Literal["full", "exception_only", "review"] = "full"
    publish_mode: Literal["manual", "auto"] = "manual"
    auto_rerun: bool = False
    max_attempts: int = Field(default=3, ge=1)


class Category(BaseModel):
    display_name: str
    keywords: list[str] = Field(min_length=1)
    subreddits: list[str] = Field(min_length=1)
    youtube_category: str | None = None


class Categories(BaseModel):
    rotation: list[str] = Field(min_length=1)
    categories: dict[str, Category] = Field(min_length=1)

    @model_validator(mode="after")
    def _rotation_known(self) -> Categories:
        unknown = [c for c in self.rotation if c not in self.categories]
        if unknown:
            raise ValueError(f"rotation references unknown categories: {unknown}")
        if len(set(self.rotation)) != len(self.rotation):
            raise ValueError("rotation contains duplicate categories")
        return self


class Voice(BaseModel):
    voice: str
    language_name: str
    channel: str


class Voices(BaseModel):
    voices: dict[str, Voice] = Field(min_length=1)


class Config(BaseModel):
    settings: Settings
    categories: Categories
    voices: Voices

    @model_validator(mode="after")
    def _cross_checks(self) -> Config:
        langs = self.settings.languages
        missing = [lang for lang in langs if lang not in self.voices.voices]
        if missing:
            raise ValueError(f"languages without a configured voice: {missing}")
        if not langs:
            raise ValueError("settings.languages must not be empty")
        return self


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - message formatting only
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")
    return raw


def load_config(config_dir: Path | str = Path("config")) -> Config:
    """Load and validate all config files from ``config_dir``.

    Raises :class:`ConfigError` on any missing file or validation problem.
    """
    base = Path(config_dir)
    try:
        settings = Settings(**_read_yaml(base / "settings.yaml"))
        categories = Categories(**_read_yaml(base / "categories.yaml"))
        voices = Voices(**_read_yaml(base / "voices.yaml"))
        return Config(settings=settings, categories=categories, voices=voices)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration in {base}: {exc}") from exc
