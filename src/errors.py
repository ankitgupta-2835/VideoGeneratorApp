"""Base exception hierarchy for the project.

All project-specific errors derive from :class:`VideoGenError` so callers can
catch everything with a single type while still distinguishing categories.
"""

from __future__ import annotations

__all__ = [
    "AgentError",
    "ConfigError",
    "ProviderError",
    "SecretsError",
    "StoreError",
    "VideoGenError",
]


class VideoGenError(Exception):
    """Base class for all project errors."""


class ConfigError(VideoGenError):
    """Configuration is missing, unreadable, or invalid."""


class SecretsError(VideoGenError):
    """Required secrets are missing or invalid."""


class ProviderError(VideoGenError):
    """An external provider/API call failed."""


class AgentError(VideoGenError):
    """An agent violated its contract or failed after retries."""


class StoreError(VideoGenError):
    """A persistence (SQLite) operation failed."""
