# Deployment runbook

Operations guide for running VideoGeneratorApp on a **$0, cloud-only** stack.
No local GPU or always-on machine is required.

## Table of Contents

- [Free stack overview & what runs where](#free-stack-overview--what-runs-where)
- [Oracle VM setup](#oracle-vm-setup)
- [Secrets matrix](#secrets-matrix)
- [Colab GPU step (hero renders)](#colab-gpu-step-hero-renders)
- [Scheduling (cron vs systemd timer vs GitHub Actions)](#scheduling-cron-vs-systemd-timer-vs-github-actions)
- [Re-runs](#re-runs)
- [Troubleshooting](#troubleshooting)

---

## Free stack overview & what runs where

| Plane | Host (all free tiers) | Runs |
|---|---|---|
| **Brain** | Oracle Cloud **Always Free** VM | Python + `ffmpeg` + the package: agents, script, TTS, assembly, publish, SQLite store |
| **GPU hero clips** | Google **Colab** (free GPU) | `notebooks/hero_render.ipynb` renders text-to-video clips |
| **Media APIs** | Pollinations / Stable Horde / Pexels / Pixabay | Free images and stock clips |
| **Scheduler** | GitHub Actions **and/or** VM cron/systemd | Triggers the daily batch |
| **Alerts / preview** | Telegram + a VM web page | Checkpoint notifications and review |
| **Secrets** | Env vars / GitHub secrets / VM `.env` | Never committed to git |

The pipeline entrypoint is **fixed**. Both forms take the same arguments:

```bash
# module form
python -m src.pipeline --category <ai_tech|finance|health_fitness|general_knowledge> [--dry-run]

# console script (installed by `pip install -e .`)
videogen --category <ai_tech|finance|health_fitness|general_knowledge> [--dry-run]
```

- `--category` selects one of the four rotating topics: **ai_tech**, **finance**,
  **health_fitness**, **general_knowledge**.
- `--dry-run` exercises the flow without publishing or uploading.

The Oracle VM never talks to Colab directly: the two exchange small JSON
documents through a shared/mounted Drive folder using the contract in
`src/visuals/render_job.py`.

## Oracle VM setup

1. Create an **Always Free** compute instance (Ubuntu, Ampere A1 or E2.1.Micro).
   Open port 22 (SSH). Open your web-preview port only if you use the preview page.
2. Copy/run the idempotent bootstrap (safe to re-run):

   ```bash
   git clone --branch main https://github.com/ankitgupta-2835/VideoGeneratorApp.git "$HOME/VideoGeneratorApp"
   bash "$HOME/VideoGeneratorApp/deploy/oracle/setup.sh"
   ```

   `deploy/oracle/setup.sh` installs `python3`, `python3-venv`, `ffmpeg`, `git`
   and `jq` via `apt`, clones/pulls the repo into `$HOME/VideoGeneratorApp`,
   creates `.venv`, runs `pip install -e .`, and copies `.env.example` to `.env`
   if absent (warning you to fill it in).

3. Fill in `.env` (see the [secrets matrix](#secrets-matrix)). It lives at
   `$HOME/VideoGeneratorApp/.env` and is git-ignored.
4. Smoke-test the brain:

   ```bash
   cd "$HOME/VideoGeneratorApp"
   .venv/bin/python -m src.pipeline --category ai_tech --dry-run
   ```

5. Schedule the daily run — see [Scheduling](#scheduling-cron-vs-systemd-timer-vs-github-actions).

## Secrets matrix

Every variable maps to a field on the `Secrets` model in `src/secrets.py`
(upper-cased) and is listed in `.env.example`. Secrets live **only** in
environment variables / GitHub secrets / the VM `.env`.

| Secret | Used by | Required? |
|---|---|---|
| `LLM_PROVIDER` | LLM client | **Yes** (defaults to `gemini`) |
| `GEMINI_API_KEY` | LLM client (`LLM_PROVIDER=gemini`) | Required if provider is gemini |
| `GROQ_API_KEY` | LLM client (`LLM_PROVIDER=groq`) | Required if provider is groq |
| `OPENROUTER_API_KEY` | LLM client (`LLM_PROVIDER=openrouter`) | Required if provider is openrouter |
| `TELEGRAM_BOT_TOKEN` | Notifier (@BotFather) | Optional (no alerts if unset) |
| `TELEGRAM_CHAT_ID` | Notifier | Optional |
| `ALERT_WEBHOOK` | Notifier (Slack/email alt.) | Optional |
| `PEXELS_API_KEY` | Stock media client | Optional (falls back / skips stock) |
| `PIXABAY_API_KEY` | Stock media client | Optional |
| `YOUTUBE_CLIENT_SECRET_EN` | Publisher (English channel) | Optional — needed for auto-publish |
| `YOUTUBE_CLIENT_SECRET_HI` | Publisher (Hindi channel) | Optional — needed for auto-publish |

Exactly one provider key must be set, matching `LLM_PROVIDER`; otherwise
`load_secrets()` raises `SecretsError` at startup.

## Colab GPU step (hero renders)

Hero clips render on a free Colab GPU. The VM and Colab communicate **only**
through JSON files in a shared Drive folder, using `src/visuals/render_job.py`
(`RenderJob`, `RenderScene`, `RenderResult`, `write_job`/`read_job`,
`write_result`/`read_result`).

1. In Google Drive, create `MyDrive/videogen/jobs/` and `MyDrive/videogen/results/`.
2. The VM writes a job there:

   ```python
   from pathlib import Path
   from src.visuals.render_job import RenderJob, RenderScene, write_job

   job = RenderJob(
       job_id="demo-job",
       scenes=[RenderScene(index=0, prompt="a slow drone shot over a city", duration_sec=5)],
   )
   write_job(job, Path("/content/drive/MyDrive/videogen/jobs"))
   ```

3. Open `notebooks/hero_render.ipynb` in Colab, choose a **GPU runtime**, mount
   Drive (the notebook calls `drive.mount('/content/drive')`), set `JOB_ID` to
   the job file's id, and run all cells.
4. The notebook writes `results/<job_id>.json` (`RenderResult.outputs` maps scene
   index → file name). The VM reads it:

   ```python
   from pathlib import Path
   from src.visuals.render_job import read_result

   result = read_result(Path("/content/drive/MyDrive/videogen/results/demo-job.json"))
   print(result.outputs)
   ```

Because both sides validate against the same pydantic models, field names,
ordering, and errors cannot drift.

## Scheduling (cron vs systemd timer vs GitHub Actions)

Pick one; they are alternatives.

### VM cron
See `deploy/oracle/videogen.cron.example`. It runs the batch in UTC (e.g.
`30 2 * * *`). Cover **all four categories** with a 4-day rotation: either call
a rotation wrapper, or use four staggered lines (one per category, each every
4 days) so exactly one category runs per day.

### systemd timer (alternative to cron)
`deploy/systemd/videogen.service` + `videogen.timer` run the same command on an
`OnCalendar` schedule with `Persistent=true` (catches up after downtime):

```bash
sudo cp deploy/systemd/videogen.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now videogen.timer
systemctl list-timers videogen.timer      # verify next run
journalctl -u videogen.service -f         # watch output
```

Adjust `--category` (or point `ExecStart` at a rotation wrapper) for cycling.

### GitHub Actions
GitHub Actions can dispatch the run via a scheduled workflow (cron syntax in
`.github/workflows/`). Use it to trigger the batch remotely or as the single
source of truth for scheduling; secrets come from **GitHub secrets**, not the
VM `.env`.

## Re-runs

A run can be re-executed at several **scopes**, handled by the re-run controller
(`src/rerun/controller.py`):

| `scope` | Re-does |
|---|---|
| `full` | The entire pipeline from topic discovery on |
| `assets` | Media generation (images / hero clips) only |
| `scenes` | Only the selected scenes |
| `new_topic` | Discards the current topic and starts a fresh one |

Exact re-run invocation follows the fixed entrypoint; run from the repo root:

```bash
cd "$HOME/VideoGeneratorApp"
# whole pipeline again
.venv/bin/python -m src.pipeline --category ai_tech
# console-script form
videogen --category ai_tech
```

Select the scope through the controller's API / the preview page as wired by the
re-run task; `new_topic` picks a different trend, `full` re-runs end-to-end, and
`assets` / `scenes` are the narrow, cheaper repairs.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `SecretsError: ... requires ..._API_KEY` | provider key missing/blank | set the key matching `LLM_PROVIDER` in `.env` |
| `python: command not found` in cron | cron PATH is minimal | use the absolute `.venv/bin/python` path (as in the examples) |
| Run never fires | wrong timezone / disabled timer | cron runs in UTC; check `systemctl list-timers` or `crontab -l` |
| `ffmpeg: not found` | system deps missing | re-run `deploy/oracle/setup.sh` |
| Colab job never returns | notebook not run / GPU quota | re-run `notebooks/hero_render.ipynb`; verify `results/<job_id>.json` exists |
| `invalid RenderJob/RenderResult` | stale/partial JSON | delete the file and regenerate; transport is atomic (`.tmp` + rename) |
| Publishes when it shouldn't | auto-publish enabled | keep `PUBLISH_MODE=manual`; leave YouTube secrets unset |
| Disk filling up | un-pruned media | clear `data/output/` and old `data/assets/*` (both git-ignored) |

Escalation order for quality issues: `scenes` → `assets` → `full` → `new_topic`.
