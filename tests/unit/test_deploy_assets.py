"""Task 5.5 tests: deploy assets, secrets template, and runbook.

These are pure file/content checks — no network, no shellcheck requirement.
Shell scripts are only syntax-checked with ``bash -n``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from src.secrets import Secrets

REPO_ROOT = Path(__file__).resolve().parents[2]

ENV_EXAMPLE = REPO_ROOT / ".env.example"
SETUP_SH = REPO_ROOT / "deploy" / "oracle" / "setup.sh"
CRON_EXAMPLE = REPO_ROOT / "deploy" / "oracle" / "videogen.cron.example"
SERVICE = REPO_ROOT / "deploy" / "systemd" / "videogen.service"
TIMER = REPO_ROOT / "deploy" / "systemd" / "videogen.timer"
DEPLOY_DOC = REPO_ROOT / "docs" / "deploy.md"
GITIGNORE = REPO_ROOT / ".gitignore"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---- 1. .env.example covers every Secrets field ---------------------------


def test_env_example_exists():
    assert ENV_EXAMPLE.is_file(), f"missing {ENV_EXAMPLE}"


def test_env_example_lists_every_secret_field():
    text = _read(ENV_EXAMPLE)
    assert Secrets.model_fields, "Secrets model exposes no fields?"
    for field in Secrets.model_fields:
        name = field.upper()
        pattern = re.compile(rf"^\s*{re.escape(name)}\s*=", re.IGNORECASE | re.MULTILINE)
        assert pattern.search(text), f"{name}= not found in .env.example"


# ---- 2. .env.example holds no obvious real secrets ------------------------


def test_env_example_has_no_obvious_real_secret():
    text = _read(ENV_EXAMPLE)
    assert "sk-" not in text, "looks like a real API key (sk- ...) in .env.example"
    # Long hex blob (e.g. a 32+ char hex secret).
    assert not re.search(r"\b[0-9a-fA-F]{32,}\b", text), "long hex blob in .env.example"
    # Long base64-ish blob.
    assert not re.search(r"[A-Za-z0-9+/]{40,}={0,2}", text), "long base64 blob in .env.example"


# ---- 3. setup.sh is valid bash --------------------------------------------


def test_setup_sh_has_bash_shebang():
    assert SETUP_SH.is_file(), f"missing {SETUP_SH}"
    first_line = _read(SETUP_SH).splitlines()[0]
    assert first_line.startswith("#!/usr/bin/env bash")


def test_setup_sh_syntax_ok():
    result = subprocess.run(
        ["bash", "-n", str(SETUP_SH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_setup_sh_is_idempotent_and_quoted():
    text = _read(SETUP_SH)
    assert "set -euo pipefail" in text
    # Re-run safety: only create the venv / .env when they are absent.
    assert re.search(r"\[\s*!\s*-x\s", text), "venv creation should be guarded"
    assert re.search(r"\[\s*!\s*-f\s", text), ".env copy should be guarded"


# ---- 4. cron example ------------------------------------------------------


def test_cron_example_contract():
    assert CRON_EXAMPLE.is_file(), f"missing {CRON_EXAMPLE}"
    text = _read(CRON_EXAMPLE)
    assert "python -m src.pipeline" in text
    assert "--category" in text
    assert "crontab" in text.lower()


# ---- 5. systemd units -----------------------------------------------------


def test_systemd_units_exist_and_timer_has_calendar():
    assert SERVICE.is_file(), f"missing {SERVICE}"
    assert TIMER.is_file(), f"missing {TIMER}"
    assert "OnCalendar" in _read(TIMER)


# ---- 6. runbook ------------------------------------------------------------


def test_deploy_doc_structure():
    assert DEPLOY_DOC.is_file(), f"missing {DEPLOY_DOC}"
    text = _read(DEPLOY_DOC)
    assert "## " in text and "Table of Contents" in text, "missing Table of Contents"
    assert "python -m src.pipeline" in text
    assert "render_job" in text
    for scope in ("new_topic", "full", "assets", "scenes"):
        assert scope in text, f"scope {scope!r} not documented"


# ---- 7. .env ignored -------------------------------------------------------


def test_gitignore_ignores_env():
    entries = {line.strip() for line in _read(GITIGNORE).splitlines()}
    assert ".env" in entries or ".env*" in entries
