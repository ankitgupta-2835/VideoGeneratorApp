"""Live smoke test for the **real** end-to-end pipeline (opt-in, never CI).

This test is a runnable skeleton: it exists to document — and, once secrets and
FFmpeg are present, to exercise — the production wiring behind
:func:`src.pipeline.stages.build_pipeline`. It is marked ``live`` and the
default ``addopts`` in ``pyproject.toml`` deselects that marker, so CI never
runs it.

How to run it for real
----------------------
1. Install the optional media/LLM extras and FFmpeg::

       pip install -e ".[dev]" edge-tts
       sudo apt-get install -y ffmpeg          # ffmpeg + ffprobe on PATH

2. Provide credentials (see ``.env.example``): at minimum an LLM key
   (``GEMINI_API_KEY`` / ``GROQ_API_KEY`` / ``OPENROUTER_API_KEY``), and
   optionally Telegram alerts and Pexels/Pixabay stock keys.

3. Select the live marker explicitly (this overrides the default ``-m``)::

       pytest -m live tests/live/test_pipeline_smoke.py -s

The pipeline still performs a *dry-run* publish (``dry_run=True``), so no video
is uploaded; set ``VGU_LIVE_SMOKE=1`` to acknowledge that and enable the run.
"""

from __future__ import annotations

import os
import shutil

import pytest

from src.pipeline.stages import build_pipeline

pytestmark = pytest.mark.live


def test_real_pipeline_smoke(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Wire the real clients and run one dry-run pass (documentation skeleton)."""
    if os.environ.get("VGU_LIVE_SMOKE") != "1":
        pytest.skip(
            "live pipeline smoke is documentation by default; set VGU_LIVE_SMOKE=1 "
            "with secrets + ffmpeg configured to run it (see module docstring)"
        )

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")

    # Imports are deferred so collecting this module never needs optional deps.
    from src.audio.tts import EdgeTTSBackend
    from src.errors import SecretsError
    from src.http_client import HttpClient
    from src.llm.client import build_llm_client
    from src.notify import build_notifier
    from src.pipeline.orchestrator import Orchestrator
    from src.secrets import load_secrets
    from src.visuals.images_pollinations import PollinationsImageClient

    try:
        secrets = load_secrets()
    except SecretsError as exc:  # no credentials configured
        pytest.skip(f"no live secrets configured: {exc}")

    http = HttpClient(cache_dir=tmp_path / "http-cache")
    stages = build_pipeline(
        llm=build_llm_client(secrets, http=http),
        notifier=build_notifier(secrets, http=http),
        tts_backend=EdgeTTSBackend(),
        image_client=PollinationsImageClient(http, tmp_path / "images"),
        http=http,
        out_dir=tmp_path / "out",
        # A real trend scout is wired by the caller from the configured sources;
        # the skeleton leaves TREND out (it is reported ``skipped``), so point a
        # full run at the real ``Supervisor`` wiring once the CLI live mode is
        # enabled.
        dry_run=True,
    )
    state = Orchestrator(stages).run("ai_tech", work_dir=tmp_path)

    # A live smoke should at least reach the content chain without crashing.
    assert state.run_id
    assert state.status in {"ok", "failed"}
