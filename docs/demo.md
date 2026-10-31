# Demo quickstart — a real video on the Oracle Always-Free VM

This is the shortest honest path from a fresh Oracle Cloud **Always Free** VM to
a **real, watchable** long-form video plus its vertical Short, using **one free
LLM key** and no local GPU. It documents the bounded **demo** mode of the
pipeline: a real end-to-end run that is deliberately small so it finishes
quickly on a free tier.

For the full production runbook (Colab hero clips, scheduling, secrets matrix)
see [`deploy.md`](deploy.md); for the stage-by-stage design see
[`architecture.md`](architecture.md).

## Table of Contents

- [What the demo produces](#what-the-demo-produces)
- [Prerequisites](#prerequisites)
- [One free LLM key](#one-free-llm-key)
- [Run it: dry-run, then demo](#run-it-dry-run-then-demo)
- [View the result](#view-the-result)
- [Re-run a bounded slice](#re-run-a-bounded-slice)
- [Free-tier reality](#free-tier-reality)
- [Troubleshooting](#troubleshooting)
- [See also](#see-also)

## What the demo produces

A successful demo run produces, under the run's attempt directory:

- a **long-form 16:9 MP4** — the assembled, captioned video (target ~4.5 min;
  the demo is bounded by `--max-scenes`), and
- a derived **9:16 Short MP4** — the vertical cut for YouTube Shorts,

together with a self-contained **HTML preview page** (a side-by-side review
sheet built by [`../src/review/build_review_page.py`](../src/review/build_review_page.py),
the task 4.3 preview) that embeds both videos so you can review them in a
browser.

### Where it lands

Every run gets a stable id and writes its media into a **non-overwriting
attempt directory**. The path is built by
[`../src/rerun/controller.py`](../src/rerun/controller.py)
(`attempt_dir(base_dir, run_id, n)` → `base_dir/<run_id>/attempt-<n>`), so by
default the demo writes to:

```
runs/<run_id>/attempt-1/...      # long 16:9 mp4, 9:16 Short, preview page
```

`run_id` is printed by the CLI at the end of the run (`run_id: ...`), and a
fresh run is `attempt-1`. Later attempts (`attempt-2`, …) live in their own
directories and never clobber attempt 1. `runs/**` is git-ignored.

## Prerequisites

1. **The VM, bootstrapped.** Create an Oracle Cloud **Always Free** compute
   instance (Ubuntu). Then run the idempotent setup script, which installs
   `python3`, `python3-venv`, **`ffmpeg`**, `git` and `jq`, clones the repo into
   `$HOME/VideoGeneratorApp`, creates `.venv`, installs the package, and seeds
   `.env`:

   ```bash
   git clone --branch main https://github.com/ankitgupta-2835/VideoGeneratorApp.git "$HOME/VideoGeneratorApp"
   bash "$HOME/VideoGeneratorApp/deploy/oracle/setup.sh"
   ```

   The script is [`../deploy/oracle/setup.sh`](../deploy/oracle/setup.sh); see
   [`deploy.md`](deploy.md#oracle-vm-setup) for the details and the optional
   preview port.

2. **Configuration from the template.**

   ```bash
   cd "$HOME/VideoGeneratorApp"
   cp .env.example .env
   ```

   `.env` is git-ignored and must never be committed. It mirrors
   [`../.env.example`](../.env.example) field-for-field.

3. **`ffmpeg` on `PATH`.** `setup.sh` installs it; verify with `ffmpeg -version`.

4. **One free LLM key** — see the next section.

## One free LLM key

The agents need exactly **one** LLM provider. `LLM_PROVIDER` selects it and the
matching key must be set; the supported free options are:

| Provider (`LLM_PROVIDER=`) | Key to set in `.env` | Where to get a free key |
|---|---|---|
| `gemini` (default) | `GEMINI_API_KEY` | Google AI Studio (Gemini API) |
| `groq` | `GROQ_API_KEY` | Groq Cloud console |
| `openrouter` | `OPENROUTER_API_KEY` | OpenRouter (free `:free` models) |

Example (Gemini):

```bash
# in .env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-free-key-here
```

Exactly one provider key must match `LLM_PROVIDER`; leaving it blank fails fast
at startup (see [Troubleshooting](#troubleshooting)). Stock-media keys
(`PEXELS_API_KEY` / `PIXABAY_API_KEY`) and Telegram keys are **optional** — the
demo runs without them.

The default Gemini model is the floating alias `gemini-flash-latest`. If you
want to pin one, set `LLM_MODEL` in `.env` (e.g. `LLM_MODEL=gemini-3.8-flash`).

## Run it: dry-run, then demo

All commands run from the repo root. The module form and the installed
`videogen` console script take the same arguments. `--category` is one of the
four keys in [`../config/categories.yaml`](../config/categories.yaml):
`ai_tech`, `finance`, `health_fitness`, `general_knowledge`.

**Step 1 — smoke test (no network, no keys, zero I/O to providers).** Confirms
the engine, config and `.env` load before spending any quota:

```bash
.venv/bin/python -m src.pipeline --category ai_tech --dry-run
```

This walks every stage with a placeholder function and writes a marker per
stage under the run directory; it makes **no** external calls.

**Step 2 — the bounded live demo.** This is a **real** run: it discovers
today's trends, calls your LLM, generates images, synthesizes narration,
captions and assembles both videos:

```bash
.venv/bin/python -m src.pipeline --category ai_tech --demo --max-scenes 6
```

`--demo` is the bounded mode. It implies:

- `--language en` (English only),
- **image-only visuals** — no hero/GPU providers are used,
- publisher `dry_run=True` — the video is prepared, **not** uploaded,
- the blueprint is capped to `--max-scenes` scenes (**default 6**).

`--max-scenes` is optional; omit it to keep the default of 6. Start smaller if
you are on a tight quota (e.g. `--max-scenes 3`).

The equivalent console-script form:

```bash
videogen --category ai_tech --demo --max-scenes 6
```

**Step 3 — full live run (no demo cap).** Once the demo looks good, drop
`--demo` to run the pipeline end-to-end for real:

```bash
.venv/bin/python -m src.pipeline --category ai_tech
```

## View the result

The CLI prints `run_id` and `work_dir`. From there:

**Copy the videos to your laptop** (e.g. with `scp`):

```bash
scp -r <user>@<vm-ip>:'~/VideoGeneratorApp/runs/<run_id>/attempt-1' ./demo-run
```

**Or review in place via the preview page.** The run writes a self-contained
HTML review sheet; serve it over any static HTTP server so you can watch the
embedded `<video>` elements in a browser:

```bash
cd "$HOME/VideoGeneratorApp"
python3 -m http.server 8000 --directory runs/<run_id>/attempt-1
# then open http://<vm-ip>:8000/  (open the preview port in the OCI security list)
```

`scp` is the simplest option; the HTTP server is only needed for the preview
page.

## Re-run a bounded slice

Rejecting a demo does not mean redoing everything. The re-run planner
([`../src/rerun/controller.py`](../src/rerun/controller.py)) replays a **scope**
and writes a fresh `attempt-<n>` directory:

| Scope | Replays from | Keeps |
|---|---|---|
| `new_topic` | `trend` (everything) | nothing — a brand-new topic |
| `full` | `angle` | the chosen topic |
| `assets` | `visuals` | script, narration and audio |
| `scenes` | `visuals`, limited to given scene indices | script, narration and audio |

Escalate repairs `scenes` → `assets` → `full` → `new_topic`. The scope is
selected through the re-run controller / preview page as wired by the re-run
task; see [`deploy.md`](deploy.md#re-runs) for the exact invocation and
[`architecture.md`](architecture.md#re-runs) for the model.

## Free-tier reality

Be honest about the free tier before you scale up:

- **LLM quotas.** Gemini, Groq and OpenRouter free tiers cap requests/minute
  and tokens/day. A demo run makes several LLM calls; a few scenes keep it
  comfortably inside the daily cap. If you hit a limit, wait or lower
  `--max-scenes`.
- **Rate limits.** Trend sources (Google Trends, Reddit, Hacker News, News RSS)
  throttle aggressively; the demo keeps limits small. A failure often means
  "the free service was busy", not "the code is broken" — re-run.
- **Image-only visuals.** `--demo` intentionally skips hero/GPU clips, so the
  result uses generated/stock images and motion. Hero text-to-video clips are a
  separate **Google Colab** step (see [`deploy.md`](deploy.md#colab-gpu-step-hero-renders))
  and are **not** part of the demo.
- **Publishing is manual.** `--demo` sets publisher dry-run, and the project
  default is `publish_mode: manual`; nothing uploads unless you wire YouTube
  OAuth secrets and opt in. Treat the demo as "produce and review", not
  "publish".
- **Live tests are opt-in.** Any `@pytest.mark.live` suite only runs with
  `RUN_LIVE=1`; a plain run never touches the network. See
  [`live-testing.md`](live-testing.md).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `SecretsError: ... requires ..._API_KEY` at startup | no LLM key set, or it does not match `LLM_PROVIDER` | set the key matching `LLM_PROVIDER` in `.env` (see [One free LLM key](#one-free-llm-key)) |
| `ProviderError: ...` mid-run | provider call failed — bad/expired key, or a free-tier rate limit | check the key and quotas; wait and re-run, or lower `--max-scenes` |
| `... -> HTTP 404: ... no longer available to new users` | the pinned Gemini model was retired | set `LLM_MODEL` in `.env` to the model named in the message (or `gemini-flash-latest`) and re-run |
| `... failed after N attempts: The read operation timed out` | the provider was slow (long prompt / model thinking) | raise the limit with `HTTP_TIMEOUT=180` in `.env` and re-run |
| `ffmpeg: not found` | system deps missing | re-run `bash deploy/oracle/setup.sh`, or `sudo apt-get install -y ffmpeg` |
| Run finds no topic / empty trends | trend sources are throttled or returned nothing | re-run later; try another `--category`; verify outbound HTTPS from the VM |
| `--demo` ignored / unknown flag | older checkout without demo support | `git pull` on the VM and re-run `setup.sh` |
| Preview page shows no video | opened the HTML without the media beside it, or stale port | serve the **attempt directory** (media + `review.html` together) over HTTP |

> **Note on error names.** Missing secrets are caught at startup and surface as
> `SecretsError` (from `load_secrets()` in `../src/secrets.py`); a bad key or a
> throttled provider surfaces later as `ProviderError` (from
> `../src/errors.py`). Both derive from `VideoGenError`.

## See also

- [`deploy.md`](deploy.md) — full Oracle VM + Colab + scheduling runbook.
- [`architecture.md`](architecture.md) — stages, gates, re-runs, free-tier split.
- [`live-testing.md`](live-testing.md) — opt-in live tests and rate-limit notes.
- [`../README.md`](../README.md) — project overview and Quickstart.
- [`../.github/workflows/daily.yml`](../.github/workflows/daily.yml) — the scheduled daily run.
