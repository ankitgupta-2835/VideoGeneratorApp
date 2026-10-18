# VideoGeneratorApp

A **$0, fully cloud-hosted** pipeline that turns a trending topic into a
scripted, narrated, captioned **YouTube video** — plus a vertical **Short** —
in **English and Hindi**, with human checkpoints and cheap re-runs when quality
isn't good enough. Everything runs on free tiers: an Oracle Cloud *Always Free*
VM for the "brain", Google Colab (free GPU) for hero clips, free image/video
APIs, GitHub Actions for scheduling/CI, and Telegram for alerts. No local GPU
and no always-on machine are required.

## Status

This is an early-stage, actively developed repository. What works **today**:

- ✅ **The pipeline engine runs end-to-end** — `python -m src.pipeline --category
  <category> --dry-run` walks every stage in order with zero network calls and
  prints a per-stage summary.
- ✅ **Supervisor contract** — stages return `ok` / `rework` / `fail`; rework is
  retried in place, failures stop the run, and checkpoint alerts fire at the
  topic / video-ready / publish boundaries.
- ✅ **Re-run planner** — deterministic scopes (`new_topic`, `full`, `assets`,
  `scenes`) with non-overwriting `attempt-<n>` directories.
- ✅ **Individual stage agents exist and are unit-tested** — trend discovery,
  angle/research, scriptwriting, localization, compliance, TTS, captions,
  visuals, motion, FFmpeg assembly, Short derivation, QA, SEO, publish.
- ⚠️ **Live publish is manual by default** and auto-upload is optional; it
  requires YouTube OAuth secrets.
- ⚠️ **Hero-GPU rendering is a Colab step** — the notebook
  (`notebooks/hero_render.ipynb`) renders text-to-video clips on a free GPU and
  exchanges JSON job/result files with the VM.
- 🚧 **Live (non-dry-run) orchestration wiring is still landing.** Until it is
  wired, a non-`--dry-run` invocation prints a message and exits non-zero; the
  `--dry-run` engine is the supported entrypoint.

> Build-time conventions (who writes what, and how) live in
> [`docs/agents.md`](docs/agents.md). Operators start at
> [`docs/deploy.md`](docs/deploy.md).

## What it does

The daily loop, on a rotating category:

1. **Discover** — scan Google Trends, Reddit, Hacker News, News RSS and YouTube
   for the strongest trending topic and score/dedup the candidates.
2. **Research & script** — pick an angle, fact-check a research brief, and write
   a scene-by-scene **blueprint** (narration, on-screen text, visual spec and
   timing per scene), then localize it to Hindi.
3. **Produce** — synthesize narration (TTS with word/scene timings), generate
   captions, route each scene to a visual tier (hero / image / stock / motion),
   render motion, and assemble the long-form video — then derive a 9:16 Short.
4. **Check** — run technical QA (black frames, silence, A/V sync) plus a quality
   critic, and pass the compliance gate (policy, copyright, monetization).
5. **Publish & learn** — generate SEO metadata and either hold for manual
   upload or (optionally) auto-publish, then feed analytics back into scoring
   weights. Alerts fire at the **topic**, **video-ready** and **publish**
   checkpoints.

## Free stack

| Plane | Host | What runs there |
|---|---|---|
| Brain (agents, FFmpeg, publish) | Oracle Cloud **Always Free** VM | Python + `ffmpeg`: agents, script, TTS, assembly, publish, SQLite store |
| GPU hero clips | Google **Colab** (free GPU) | `notebooks/hero_render.ipynb` renders text-to-video clips |
| Free image / video APIs | Pollinations · Stable Horde · Pexels · Pixabay | Scene images and stock clips |
| Scheduler / CI | GitHub Actions + VM cron/systemd | Daily dispatch, lint, type-check and tests |
| Alerts / preview | Telegram + a VM web page | Checkpoint notifications and side-by-side preview |

## Architecture (high level)

Stages run in a fixed canonical order. The supervisor drives each one, carries
its artifact forward, and applies the `ok` / `rework` / `fail` contract:

```
 trend ─▶ angle ─▶ research ─▶ script ─▶ localize ─▶ compliance
                                                          │
        ┌─────────────────────────────────────────────────┘
        ▼
      voice ─▶ captions ─▶ visuals ─▶ motion ─▶ assemble ─▶ short ─▶ qa ─▶ seo ─▶ publish
```

Checkpoint alerts fire after **trend** (topic), **assemble** (video-ready) and
**publish**. `compliance` and `qa` are gates that can send a run back for
rework or stop it. A full, stage-by-stage contract — owning agents, inputs and
outputs, gates, re-run scopes and attempt versioning — is in
[`docs/architecture.md`](docs/architecture.md).

## Quickstart

```bash
# 1. Clone and enter the repo
git clone https://github.com/ankitgupta-2835/VideoGeneratorApp.git
cd VideoGeneratorApp

# 2. Create a virtual environment and install (editable, with dev tools)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Provide configuration (fill in keys; never commit .env)
cp .env.example .env

# 4. Run the pipeline engine end-to-end with no external calls
python -m src.pipeline --category ai_tech --dry-run

# ...or the installed console script, which is equivalent
videogen --category ai_tech --dry-run
```

The module form and the `videogen` console script take the same arguments:
`--category` (one of `ai_tech`, `finance`, `health_fitness`,
`general_knowledge`), `--language` (`en` or `hi`), `--dry-run`, and
`--work-dir`. `--dry-run` needs no API keys and writes a marker file per stage
under `runs/<run_id>/stages/`.

## Configuration

- **Secrets / environment** — copy [`.env.example`](.env.example) to `.env` and
  fill it in. Every variable maps to a field on the `Secrets` model in
  [`src/secrets.py`](src/secrets.py). The key groups are `LLM_PROVIDER` plus the
  matching provider key (`GEMINI_API_KEY` / `GROQ_API_KEY` /
  `OPENROUTER_API_KEY`), optional Telegram alerts (`TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID`, `ALERT_WEBHOOK`), stock media (`PEXELS_API_KEY`,
  `PIXABAY_API_KEY`) and optional YouTube OAuth
  (`YOUTUBE_CLIENT_SECRET_EN` / `YOUTUBE_CLIENT_SECRET_HI`). Exactly one
  provider key must be set, matching `LLM_PROVIDER`.
- **Behaviour** — checked-in YAML under [`config/`](config):
  `categories.yaml` (the four rotating categories and their keywords/subreddits),
  `settings.yaml` (paths, video durations/aspect ratios, languages, publish
  mode, autonomy) and `voices.yaml` (per-language narration voice and channel).

## Re-runs

Rejecting a run replays only as much as needed. The planner in
[`src/rerun/controller.py`](src/rerun/controller.py) supports four **scopes**:

| Scope | Re-plays from | Keeps |
|---|---|---|
| `new_topic` | `trend` (everything) | nothing — a brand-new topic |
| `full` | `angle` | the chosen topic |
| `assets` | `visuals` | script, narration and audio |
| `scenes` | `visuals`, limited to given scene indices | script, narration and audio |

Every attempt is written to a fresh, 1-based `attempt-<n>` directory, so an
earlier attempt is never overwritten. Escalate quality repairs
`scenes` → `assets` → `full` → `new_topic`.

## Development & testing

```bash
ruff check .          # lint
black --check .       # formatting
mypy                  # type-check src/
pytest                # unit + integration tests (mocked; no network)

# Opt-in tests that hit real external services (never run in CI)
RUN_LIVE=1 pytest -m live
```

Tests use fakes/mocks and do not touch the network by default; tests marked
`@pytest.mark.live` are opt-in via `RUN_LIVE=1 pytest -m live`. CI
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs ruff, black,
mypy and pytest on every push to `main` and every pull request.

## Project layout

```
config/      YAML config (categories, voices, settings)
src/         package
  agents/      runtime agents (trend_scout, research, scriptwriter, qa_critic, …)
  trends/      trend sources + scorer
  schema/      shared data contracts (blueprint)
  audio/       TTS + timing
  visuals/     image/horde/stock/hero/motion providers
  assemble/    captions, FFmpeg assembly, Short derivation
  qa/          technical checks
  rerun/       re-run planner (scopes + attempt versioning)
  review/      preview page builder
  publish/     publish helpers
  store/       SQLite run/alert store
  pipeline/    orchestrator + CLI (`videogen`)
tests/       unit | integration | live | fixtures | golden
docs/        agents.md, architecture.md, deploy.md
deploy/      Oracle VM setup, cron/systemd units
notebooks/   hero_render.ipynb (Colab GPU)
```

## Deployment

The operational runbook for a $0, cloud-only deployment — Oracle VM setup,
secrets matrix, the Colab GPU step, and scheduling via cron / systemd /
GitHub Actions — is in [`docs/deploy.md`](docs/deploy.md).

## License

MIT — see [`LICENSE`](LICENSE).
