# GitHub Actions host — no credit card required

This is the recommended **$0 host** for VideoGeneratorApp. GitHub Actions runs
the whole CPU pipeline — trend discovery, LLM agents, TTS, FFmpeg, assembly,
Short derivation, QA and SEO — on a free Ubuntu runner. No VM, no card, and no
always-on machine is needed.

The workflow is [`.github/workflows/daily.yml`](../.github/workflows/daily.yml).
It is a **daily batch**, which is the right shape for this project: GitHub
Actions is not a persistent server, and the pipeline does not need one.

> Oracle Cloud Always Free requires a credit/debit card (Visa/Mastercard/Amex)
> for identity verification. If you do not have an eligible card, use this page
> instead; the Oracle files under `deploy/` are legacy and are not required.

## What runs where

| Plane | Host | Runs |
|---|---|---|
| **Brain** | **GitHub Actions** (Ubuntu runner) | Python + `ffmpeg`: agents, TTS, assembly, publish metadata, SQLite store |
| **GPU hero clips** (optional) | **Kaggle** or **Colab** | `RenderJob` contract + `notebooks/hero_render.ipynb` |
| **Media APIs** | Pollinations / Cloudflare / Stable Horde / Pexels / Pixabay | Images and stock clips |
| **Scheduler** | **GitHub Actions cron** | Daily 07:00 IST run + manual dispatch |
| **Alerts** | Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) | Checkpoint and failure alerts |
| **Outputs** | Actions artifacts + GitHub Releases | Review bundle, MP4s, zip |

## One-time setup

### 1. Repository

Push the repo to GitHub. A **public** repository gets free standard-runner
minutes with no monthly cap (fair use); a private repository gets **2,000
free minutes/month** on the Free plan. Secrets are stored in GitHub, never in
the code, so a public repo is safe.

### 2. Secrets

Go to **Settings → Secrets and variables → Actions → Secrets** and add the
ones you use:

| Secret | Required? | Used by |
|---|---|---|
| `GEMINI_API_KEY` | Yes, if `LLM_PROVIDER=gemini` (default) | LLM client |
| `GROQ_API_KEY` | If `LLM_PROVIDER=groq` | LLM client |
| `OPENROUTER_API_KEY` | If `LLM_PROVIDER=openrouter` | LLM client |
| `OPENAI_API_KEY` | If `LLM_PROVIDER=openai` | LLM client |
| `TELEGRAM_BOT_TOKEN` | Optional | Checkpoint + failure alerts |
| `TELEGRAM_CHAT_ID` | Optional | Alerts |
| `ALERT_WEBHOOK` | Optional | Non-Telegram alert sink |
| `PEXELS_API_KEY` | Optional | Stock media |
| `PIXABAY_API_KEY` | Optional | Stock media |
| `POLLINATIONS_TOKEN` | Optional | Lifts the Pollinations image limit |
| `CLOUDFLARE_ACCOUNT_ID` | Optional | Second free image provider |
| `CLOUDFLARE_API_TOKEN` | Optional | Second free image provider |
| `YOUTUBE_CLIENT_SECRET_EN` / `_HI` | Optional | Auto-publish only (manual by default) |

Exactly one LLM provider key must match `LLM_PROVIDER`, otherwise the run fails
fast with `SecretsError`.

### 3. Variables

Go to **Settings → Secrets and variables → Actions → Variables** for the
non-secret settings:

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini`, `groq`, `openrouter`, or `openai` |
| `LLM_MODEL` | provider default | Pin a model (e.g. `gemini-flash-latest`) |
| `LLM_BASE_URL` | — | Required for `LLM_PROVIDER=openai` |
| `HTTP_TIMEOUT` | `90` | Per-request timeout in seconds |

The workflow falls back to same-named **secrets** for these four values, so an
existing `LLM_PROVIDER` secret (from the old dry-run workflow) keeps working.
Prefer variables for non-secret settings.

## Run it

### Manual dry-run (no keys)

1. Open **Actions → Daily video → Run workflow**.
2. Choose `mode: dry-run`, `category: auto`, `languages: en`.
3. Run it. This exercises every stage with placeholder functions and needs no
   API keys, so it is the safest way to confirm the workflow itself is wired.

### Manual demo (cheap live smoke test)

1. Choose `mode: demo`, `category: auto`, `languages: en` (demo is always
   English), `max_scenes: 6`.
2. Run it. A successful run produces a long MP4 and a 9:16 Short.

Manual runs default to `demo` on purpose: it is bounded, image-only, and
dry-run publishes, so it spends very little API quota.

### Scheduled production run

The cron is **01:30 UTC = 07:00 IST**, matching `config/settings.yaml`. It runs
`mode: full` for the date's category in **both languages** (`en` and `hi`).
The category comes from `python -m src.pipeline.schedule`, which cycles
`ai_tech → finance → health_fitness → general_knowledge` by calendar day.

GitHub cron is UTC and may start a few minutes late at peak times. Scheduled
workflows only run on the repository's **default branch**.

## Where the outputs are

Every run publishes two things:

- **Artifacts** (14 days): `pipeline.log`, `review.html`, manifests, captions,
  and narration audio. Open **Actions → the run → Artifacts**.
- **A GitHub Release** tagged `run-<number>`: a zip of the complete `runs/`
  folder (unzip and open `runs/<run_id>/review.html` beside the media), plus
  each `video.mp4` and `short.mp4` with a unique name. Open **Releases** to
  download or share.

Release assets are permanent until you delete the release. A 4–5 minute 1080p
MP4 is well under GitHub's 2 GB per-asset limit.

## State and caching

The pipeline keeps a small SQLite history at `data/history.db` (topic dedupe,
run/attempt bookkeeping) and a provider cache under `data/assets/cache`. The
workflow restores both with `actions/cache`:

```yaml
key: videogen-state-${{ github.run_id }}
restore-keys: videogen-state-
```

Each run saves a new cache entry and restores the most recent one. If the cache
is evicted (7 days unused) or the 10 GB per-repo cache limit is reached, the
run still succeeds; it just loses dedupe history and re-downloads media. To
reset state deliberately, delete the `videogen-state-*` caches under
**Actions → Caches**.

## Free-tier limits (be honest)

| Limit | Value |
|---|---|
| Private repo minutes | 2,000/month (Free plan) |
| Public repo minutes | Free within fair use |
| Job timeout | 6 hours (the workflow caps at 4) |
| Runner disk | ~14 GB SSD |
| Runner RAM | ~16 GB on public repos, ~7 GB on private free tier |
| Artifact retention | 14 days (configured) |

A demo run is a few minutes. A full two-language run is typically 20–45 minutes
depending on LLM/TTS/image latency, so **private repos can approach the 2,000
minutes/month** (60 min/day × 30). Prefer a public repo, or run `hi` on alternate
days, or use `--max-scenes`/720p for a while.

## Optional: Kaggle as the GPU worker

The daily workflow is CPU-only and does **not** use a GPU. Hero text-to-video
clips remain optional:

- The contract is [`src/visuals/render_job.py`](../src/visuals/render_job.py)
  (`RenderJob` / `RenderResult`).
- Run the renderer in a Kaggle notebook (free T4) or the existing
  [`notebooks/hero_render.ipynb`](../notebooks/hero_render.ipynb) on Colab.
- Trigger it manually, or from a separate `workflow_dispatch` workflow using
  the Kaggle API (`KAGGLE_USERNAME` + `KAGGLE_KEY` secrets):
  `kaggle kernels push -p <notebook-dir>`.

Keep the daily host on Actions; treat Kaggle as a batch GPU step, not a
persistent service.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `SecretsError: ... requires ..._API_KEY` | missing/wrong provider key | set the secret matching `LLM_PROVIDER` |
| Scheduled run never starts | workflow not on the default branch, or Actions disabled | merge to `main`; check **Actions** is enabled |
| Run starts late | GitHub cron queue | expected at peak; use `workflow_dispatch` for a fixed time |
| `ffmpeg: not found` | install step skipped/failed | re-run the workflow; the install step is mandatory |
| `Release` step fails | token lacks write access / tag exists | `permissions: contents: write` is already set; a re-run uploads with `--clobber` |
| Outputs missing after success | no video was produced | inspect `pipeline.log` in the run artifacts |
| State resets | cache evicted | expected; dedupe history re-learns from scratch |
| `The read operation timed out` | slow free LLM | raise the `HTTP_TIMEOUT` repository variable |

## See also

- [`deploy.md`](deploy.md) — secrets matrix, GPU step, re-runs.
- [`demo.md`](demo.md) — bounded demo walkthrough.
- [`architecture.md`](architecture.md) — stages, gates, and the free-tier split.
- [`../.github/workflows/daily.yml`](../.github/workflows/daily.yml) — the workflow.
