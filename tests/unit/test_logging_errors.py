"""Task 0.5 tests: exception hierarchy and logging setup."""

from __future__ import annotations

import io
import logging

from src import config as config_mod
from src import secrets as secrets_mod
from src.errors import (
    AgentError,
    ConfigError,
    ProviderError,
    SecretsError,
    StoreError,
    VideoGenError,
)
from src.logging_setup import configure_logging, get_logger


def test_all_errors_share_base():
    for exc in (ConfigError, SecretsError, ProviderError, AgentError, StoreError):
        assert issubclass(exc, VideoGenError)


def test_config_and_secrets_reuse_shared_errors():
    assert config_mod.ConfigError is ConfigError
    assert secrets_mod.SecretsError is SecretsError


def test_configure_logging_writes_to_stream():
    buf = io.StringIO()
    configure_logging("INFO", stream=buf, force=True)
    get_logger("demo").info("hello world")
    out = buf.getvalue()
    assert "hello world" in out
    assert "INFO" in out
    assert "demo" in out


def test_configure_logging_respects_level():
    buf = io.StringIO()
    configure_logging("WARNING", stream=buf, force=True)
    log = get_logger("demo.level")
    log.info("should be hidden")
    log.warning("should appear")
    out = buf.getvalue()
    assert "should be hidden" not in out
    assert "should appear" in out


def test_configure_logging_is_idempotent():
    configure_logging(force=True)
    configure_logging()
    configure_logging()
    ours = [h for h in logging.getLogger().handlers if getattr(h, "_videogen_handler", False)]
    assert len(ours) == 1


def test_get_logger_is_namespaced():
    assert get_logger("a.b.c").name == "a.b.c"
