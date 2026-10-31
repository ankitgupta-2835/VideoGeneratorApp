# Deployment runbook

Operations guide for running VideoGeneratorApp on a **$0, cloud-only** stack.
The recommended host is **GitHub Actions** — no credit card, no VM, no local
GPU. Kaggle/Colab remain optional GPU workers for hero clips.

## Table of Contents

- [Free stack overview & what runs where](#free-stack-overview--what-runs-where)
- [GitHub Actions setup (no card)](#github-actions-setup-no-card)
- [Secrets matrix](#secrets-matrix)
- [GPU step: Kaggle or Colab (optional)](#gpu-step-kaggle-or-colab-optional)
- [Scheduling](#scheduling)
- [Re-runs](#re-runs)
- [Troubleshooting](#troubleshooting)

---

## Free stack overview & what runs where

| Plane | Host (all free tiers) | Runs |
|---|---|---|
| **Brain** | **GitHub Actions** (Ubuntu runner) | Python + `ffmpeg`: agents, script, TTS, assembly, publish metadata, SQLite store |
| **GPU hero clips** (optional) | **Kaggle** or **Colab** | `RenderJob` contract + `notebooks/hero_render.ipynb` |
| **Media APIs** | Pollinations / Cloudflare / Stable Horde / Pexels / Pixabay | Free images and stock clips |
| **Scheduler** | **GitHub Actions cron** | Daily batch + manual `workflow_dispatch` |
| **Alerts / preview** | Telegram + the review page in the run zip | Checkpoint notifications and review |
| **Secrets** | GitHub secrets / repository variables | Never committed to git |

The pipeline entrypoint is **fixed**. Both forms take the same arguments:

```bash
# module form
python -m src.pipeline --category <ai_tech|finance|health_fitness|general_knowledge> [--dry-run]

# console script (installed by `pip install -e .`)
videogen --category <ai_tech|finance|health_fitness|general_knowledge> [--dry-run]
```

- `--category` selects one of the four rotating topics: **ai_tech**, **finance**,
  **health_fitness**, **general_knowledge**.
- `--language` is `en` or `hi`; `--demo` forces English.
- `--dry-run` exercises the flow without network calls or publishing.
- `--demo` is a bounded live run: image-only visuals, dry-run publish, and
  `--max-scenes` (default 6).

The daily host and the optional GPU worker never talk directly: they exchange
small JSON job/result documents through the contract in
`src/visuals/render_job.py`.

## GitHub Actions setup (no card)

The full step-by-step guide is [`actions.md`](actions.md). The short version:

1. Push the repo to GitHub. A **public** repo is free; a private repo gets
   2,000 free Actions minutes/month.
2. Add **secrets** under *Settings → Secrets and variables → Actions →
   Secrets*: the LLM key (`GEMINI_API_KEY`, `GROQ_API_KEY`, …), optionally
   Telegram, stock, Pollinations, and Cloudflare keys.
3. Add **variables** for non-secret settings: `LLM_PROVIDER`, `LLM_MODEL`,
   `LLM_BASE_URL`, `HTTP_TIMEOUT`.
4. Open **Actions → Daily video → Run workflow** and choose `mode: demo` for a
   cheap first run.
5. The scheduled run (01:30 UTC = 07:00 IST) does a **full** run for the date's
   category in **both languages**. Outputs land in the run's **Artifacts** and
   in a **GitHub Release** tagged `run-<number>` (zip + MP4s).

State (`data/history.db`) and the provider cache are restored with
`actions/cache`, so topic dedupe survives between runs. If the cache is
evicted, the run still succeeds and re-learns.

## Secrets matrix

Every variable maps to a field on the `Secrets` model in `src/secrets.py`
(upper-cased) and is listed in `.env.example`. Secrets live **only** in GitHub
secrets / repository variables, or a local `.env` for development.

| Secret | Used by | Required? |
|---|---|---|
| `LLM_PROVIDER` | LLM client (repository **variable**) | **Yes** (defaults to `gemini`) |
| `GEMINI_API_KEY` | LLM client (`LLM_PROVIDER=gemini`) | Required if provider is gemini |
| `GROQ_API_KEY` | LLM client (`LLM_PROVIDER=groq`) | Required if provider is groq |
| `OPENROUTER_API_KEY` | LLM client (`LLM_PROVIDER=openrouter`) | Required if provider is openrouter |
| `OPENAI_API_KEY` | LLM client (`LLM_PROVIDER=openai`) | Required if provider is openai |
| `LLM_BASE_URL` | OpenAI-compatible endpoint (repository variable) | Required for `openai` |
| `LLM_MODEL` | Model override (repository variable) | Required for `openai` |
| `HTTP_TIMEOUT` | Per-request timeout (repository variable) | Optional (default 90s) |
| `TELEGRAM_BOT_TOKEN` | Notifier (@BotFather) | Optional (no alerts if unset) |
| `TELEGRAM_CHAT_ID` | Notifier | Optional |
| `ALERT_WEBHOOK` | Notifier (Slack/email alt.) | Optional |
| `PEXELS_API_KEY` | Stock media client | Optional |
| `PIXABAY_API_KEY` | Stock media client | Optional |
| `POLLINATIONS_TOKEN` | Pollinations image limit | Optional |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare Workers AI fallback images | Optional |
| `CLOUDFLARE_API_TOKEN` | Cloudflare Workers AI fallback images | Optional |
| `YOUTUBE_CLIENT_SECRET_EN` | Publisher (English channel) | Optional — auto-publish only |
| `YOUTUBE_CLIENT_SECRET_HI` | Publisher (Hindi channel) | Optional — auto-publish only |

Exactly one provider key must be set, matching `LLM_PROVIDER`; otherwise
`load_secrets()` raises `SecretsError` at startup. Publishing is **manual** by
default, so YouTube secrets are not needed for normal runs.

## GPU step: Kaggle or Colab (optional)

Hero clips are optional. The daily Actions run is CPU-only and produces a
complete video from generated/stock images plus motion. If you want
text-to-video clips, render them on a free GPU.

Both Kaggle and Colab use the same contract:

- [`src/visuals/render_job.py`](../src/visuals/render_job.py) defines
  `RenderJob`, `RenderScene`, `RenderResult`, and the atomic JSON transport.
- [`notebooks/hero_render.ipynb`](../notebooks/hero_render.ipynb) is the Colab
  template; the same cells run on Kaggle after copying the job JSON into
  `/kaggle/working` (or attaching it as a Kaggle Dataset).

1. Create a job JSON with the scene prompts and durations.
2. Run the notebook on a GPU runtime; it writes the clips plus a
   `RenderResult` JSON.
3. Download the results (Colab: Drive; Kaggle: *Save Version* → Output).
4. Add the clips as hero assets on the next run.

To trigger Kaggle from Actions, keep it in a **separate** `workflow_dispatch`
workflow so the daily CPU run is never blocked by GPU queueing:

```bash
pip install kaggle
kaggle kernels push -p path/to/kernel-dir
kaggle kernels status <user>/<kernel>
kaggle kernels output <user>/<kernel> -p ./hero-out
```

Store `KAGGLE_USERNAME` and `KAGGLE_KEY` as GitHub secrets. The Kaggle API
does not require a credit card; downloads count against your Kaggle quota.

## Scheduling

GitHub Actions is the single scheduler. The workflow is
[`.github/workflows/daily.yml`](../.github/workflows/daily.yml):

- **Schedule:** `30 1 * * *` UTC (07:00 IST), full run, both languages, date
  rotation.
- **Manual:** `workflow_dispatch` with `mode` (`dry-run` / `demo` / `full`),
  `category` (`auto` or a fixed key), `languages` (`both` / `en` / `hi`), and
  `max_scenes` for demos.
- **Category rotation:** `python -m src.pipeline.schedule` — a pure function of
  the UTC date, cycling the four categories.
- **Concurrency:** one run at a time (`group: daily-video`), so state and
  releases never race.

If you already operate your own VM, the legacy helpers under `deploy/` still
work, but they are not part of the supported no-card path. Prefer the workflow.

## Re-runs

A run can be re-executed at several **scopes**, handled by the re-run controller
(`src/rerun/controller.py`):

| `scope` | Re-does |
|---|---|
| `full` | The entire pipeline from topic discovery on |
| `assets` | Media generation (images / hero clips) only |
| `scenes` | Only the selected scenes |
| `new_topic` | Discards the current topic and starts a fresh one |

Re-run from the Actions **Run workflow** button for a fresh batch, or locally /
on a VM with the fixed entrypoint:

```bash
python -m src.pipeline --category ai_tech
videogen --category ai_tech
```

Select the scope through the controller's API / the preview page as wired by the
re-run task; `new_topic` picks a different trend, `full` re-runs end-to-end, and
`assets` / `scenes` are the narrow, cheaper repairs.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `SecretsError: ... requires ..._API_KEY` | provider key missing/blank | set the secret matching `LLM_PROVIDER` |
| Scheduled run never starts | workflow not on the default branch, or Actions disabled | merge to `main`; enable Actions |
| Run starts late | GitHub cron queue | expected at peak; use `workflow_dispatch` for a fixed time |
| `ffmpeg: not found` | install step failed | re-run the workflow; the apt step installs ffmpeg |
| `Release` step fails | tag collision / token permission | a re-run uploads with `--clobber`; `contents: write` is set |
| No outputs after a successful run | pipeline produced no video | read `pipeline.log` in the run artifacts |
| State resets | Actions cache evicted | expected; dedupe history re-learns |
| `The read operation timed out` | slow free LLM | raise the `HTTP_TIMEOUT` variable |
| Colab/Kaggle job never returns | notebook not run / GPU quota | re-run the notebook; verify `RenderResult` exists |
| `invalid RenderJob/RenderResult` | stale/partial JSON | delete the file and regenerate; transport is atomic |
| Publishes when it shouldn't | auto-publish enabled | keep manual publishing; leave YouTube secrets unset |

Escalation order for quality issues: `scenes` → `assets` → `full` → `new_topic`.
