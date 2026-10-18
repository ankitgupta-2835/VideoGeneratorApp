# VideoGeneratorApp

Free-of-cost, **fully cloud-hosted** pipeline that, on a daily schedule:

1. Finds the most trending topic in a rotating category.
2. Writes a detailed, scene-by-scene **script blueprint** for video generation.
3. Generates a ~4–5 min long-form video + a derived Short, in **English and Hindi**.
4. Alerts you at the **topic**, **video-ready**, and **publish** checkpoints.
5. Lets you **re-run** the whole process or specific scenes if quality isn't good enough.

Publishing is **manual by default** (you post) and auto-upload is optional.

> Status: early scaffold. See the build plan in
> `~/.opencode/plan/video-generator-app-workflow.md` (tasks are built one at a time,
> each tested before it is pushed).

## Architecture (high level)

Compute is split across free tiers so no local GPU/CPU is required:

| Plane | Host |
|---|---|
| Brain (agents, FFmpeg, publish) | Oracle Cloud Always Free VM |
| GPU hero clips | Google Colab free |
| Free image/video APIs | Pollinations / Stable Horde / Pexels |
| Scheduler / dispatch | GitHub Actions |
| Alerts / preview | Telegram + VM web page |

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # fill in keys; never commit .env

ruff check .
black --check .
mypy
pytest
```

Tests use fakes/mocks and never hit the network. Real-API tests are marked
`@pytest.mark.live` and are opt-in (`pytest -m live`).

## Layout

```
config/     YAML config (categories, voices, settings)
src/        package: agents, trends, script, audio, visuals, assemble, qa, rerun, review, publish, store
tests/      unit | integration | live | fixtures | golden
```
