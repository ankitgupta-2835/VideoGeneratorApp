# Architecture

This document describes how VideoGeneratorApp is put together: the canonical
**stage flow**, the **agents** that own each stage, the shared **data
contracts**, the **supervisor contract** (`ok` / `rework` / `fail`), the
**re-run** model, and the **free-tier deployment** in brief. For the
operational runbook see [`deploy.md`](deploy.md); for build-time agent
conventions see [`agents.md`](agents.md).

## Table of Contents

- [Stage flow](#stage-flow)
- [Stage reference](#stage-reference)
- [Data contracts](#data-contracts)
- [Supervisor contract](#supervisor-contract)
- [Gates, checkpoints and alerts](#gates-checkpoints-and-alerts)
- [Re-runs](#re-runs)
- [Free-tier deployment](#free-tier-deployment)

## Stage flow

The pipeline is a fixed, ordered sequence defined by `Stage` and
`STAGE_ORDER` in [`../src/rerun/controller.py`](../src/rerun/controller.py).
Stage ordering is the enum's **definition order**, not alphabetical. The
supervisor iterates `STAGE_ORDER`, initialises every stage to `pending`, and
carries each stage's artifact forward for later stages to consume.

```
 trend ─▶ angle ─▶ research ─▶ script ─▶ localize ─▶ compliance
                                                          │
        ┌─────────────────────────────────────────────────┘
        ▼
      voice ─▶ captions ─▶ visuals ─▶ motion ─▶ assemble ─▶ short ─▶ qa ─▶ seo ─▶ publish
```

The three **checkpoint** boundaries (topic / video-ready / publish) are marked
below; gates (`compliance`, `qa`) can send a run back for rework or stop it.

## Stage reference

Each stage's `value` is its key in `RunState.stages`. The *build agent* column
names the owning subagent from [`agents.md`](agents.md); the *module* column is
the code that implements the runtime agent or helper.

| Stage (`value`) | Build agent | Module | Input → Output contract | Gate / checkpoint |
|---|---|---|---|---|
| `trend` | Pythia (trend discovery) | [`trend_scout.py`](../src/agents/trend_scout.py) | `ScoutInput` → `TopicCandidates` | **Checkpoint** — topic |
| `angle` | Melete (ideation / research) | [`angle_strategist.py`](../src/agents/angle_strategist.py) | `TopicCandidates` → `ChosenAngle` | — |
| `research` | Melete (ideation / research) | [`research.py`](../src/agents/research.py) | `ChosenAngle` → `ResearchBrief` | — |
| `script` | Calliope (narrative / script) | [`scriptwriter.py`](../src/agents/scriptwriter.py) | `ScriptRequest` → `Blueprint` | Advisory: [`script_director.py`](../src/agents/script_director.py) (`DirectorInput` → `DirectorReport`, may request `rework`) |
| `localize` | Polyhymnia (localization) | [`localizer.py`](../src/agents/localizer.py) | `Blueprint` → `Blueprint` (Hindi) | — |
| `compliance` | Sentinel (trust & safety) | [`compliance.py`](../src/agents/compliance.py) | `ComplianceInput` → `ComplianceReport` | **Gate** — policy / copyright / monetization (`rework` on blocking flags) |
| `voice` | Orpheus (audio / TTS) | [`voice_director.py`](../src/agents/voice_director.py) | `VoiceInput` → `AudioTrack` | — |
| `captions` | Daedalus (media / assembly) | [`captions.py`](../src/assemble/captions.py) | `AudioTrack` timings → SRT / ASS cues | — |
| `visuals` | Pygmalion → Daedalus (visuals) | [`visual_director.py`](../src/agents/visual_director.py) | `VisualInput` → `SceneAssets` | — |
| `motion` | Daedalus (media / assembly) | [`motion.py`](../src/visuals/motion.py) | still image + duration → motion clip | — |
| `assemble` | Daedalus (media / assembly) | [`ffmpeg.py`](../src/assemble/ffmpeg.py) | scenes + `AudioTrack` → long-form video | **Checkpoint** — video-ready |
| `short` | Daedalus (media / assembly) | [`short.py`](../src/assemble/short.py) | long-form video → 9:16 Short | — |
| `qa` | Sentinel (trust & safety) | [`qa_critic.py`](../src/agents/qa_critic.py) | `QaInput` → `QaReport` | **Gate** — technical + quality (`passed` / score threshold) |
| `seo` | Janus (publishing / SEO) | [`seo.py`](../src/agents/seo.py) | `SeoInput` → `PublishMetadata` | — |
| `publish` | Janus (publishing / SEO) | [`publisher.py`](../src/agents/publisher.py) | `PublishInput` → `PublishResult` | **Checkpoint** — publish |

Two adjacent helpers support the flow but are not stages themselves:
[`checks.py`](../src/qa/checks.py) runs the technical video checks that feed the
`qa` gate, and [`revision_director.py`](../src/agents/revision_director.py)
turns reviewer feedback into a revision plan that drives the re-run scopes.

## Data contracts

The stages hand each other typed, validated pydantic models rather than ad-hoc
dictionaries. The load-bearing ones:

| Contract | Module | What it carries |
|---|---|---|
| **Blueprint** / **Scene** | [`blueprint.py`](../src/schema/blueprint.py) | The scene-by-scene script: `Meta` (title, category, language, target duration, angle, sources) plus ordered `Scene`s, each with `narration`, `on_screen_text`, a `VisualSpec` (`hero` / `image` / `stock` / `motion`), `duration_sec` and a `hero` flag. `validate_blueprint` adds relational checks (index sequence, total duration vs a `TimingBudget`, hero ratio, scene count, on-screen-text length). |
| **AudioTrack** | [`tts.py`](../src/audio/tts.py) | Synthesized narration `path`, `voice`, `language`, `duration_sec`, and a timing map: `words` (`WordTiming`) and `scenes` (`SceneTiming`). |
| **SceneAssets** | [`visual_director.py`](../src/agents/visual_director.py) | The ordered visuals produced for the blueprint: `SceneAsset` entries (`index`, `kind`, `path`, `provider`). |
| **QaReport** | [`qa_critic.py`](../src/agents/qa_critic.py) | The QA gate's verdict: `score` (0–100), `passed`, `technical_issues`, `critiques`, `notes`. |
| **PublishMetadata** | [`seo.py`](../src/agents/seo.py) | Publish-ready metadata: `title`, `description`, `tags`, `thumbnail_prompt`, `language`. |

## Supervisor contract

Every stage function is invoked by
[`Orchestrator`](../src/pipeline/orchestrator.py) and returns a `StageResult`
whose `status` is one of **`ok`**, **`rework`** or **`fail`**:

- **`ok`** — the stage succeeded, the orchestrator records it `ok`, appends the
  stage value to `completed`, and stores its `artifact` (if any) on the
  `RunState` and the shared `RunContext` so later stages can consume it.
- **`rework`** — the stage is retried **in place**; `max_rework` is the number
  of *retries after the first attempt*, so a stage runs at most
  `max_rework + 1` times (`max_rework` defaults to `2`). If rework is still
  requested after the retries, the stage is recorded `fail` and the run stops.
  The orchestrator never blocks waiting for a human.
- **`fail`** — the stage is recorded `fail` (with the reason in `notes`) and the
  run stops. Any exception raised by a stage function, or a return value that
  is not a `StageResult`, is treated the same way.

A stage with **no wired function** is recorded `skipped` — *not* a failure — so
a partially wired pipeline still runs. `RunState.status` is `ok` only if every
**wired** stage reached `ok`; skipped stages do not block, and any failure makes
it `failed`.

The lower-level [`Supervisor`](../src/agents/base.py) wraps individual agents
with the same three-valued vocabulary: an `AgentResult(status="fail")` is retried
up to the agent's `max_retries` and then returned, while `rework` is handed back
to the caller (a gate) to decide.

When a `Database` store is supplied, the orchestrator calls `create_run` at the
start, `set_run_status` at the end, and `record_alert` for each checkpoint.
Persistence and alerting failures are caught and noted, never fatal.

### Gates, checkpoints and alerts

**Gates** can send a run back for revision or stop it:

- `compliance` returns `rework` when a blocking policy flag is present (banned
  medical/financial claims, copyright sources outside the allow-list, …) so the
  narrative stage can revise the offending scene.
- `qa` combines deterministic technical checks (black frames, silence, A/V
  desync — see [`checks.py`](../src/qa/checks.py)) with a quality critic; its
  `QaReport.passed` / `score` decides whether the video clears the bar.

**Checkpoints** (`CHECKPOINTS`) fire a human alert once the stage completes OK:

| Stage | Checkpoint | Alert |
|---|---|---|
| `trend` | `topic` | candidate topic found (review/approve) |
| `assemble` | `video` | video-ready for review |
| `publish` | `publish` | published / held for manual publish |

Alerts go through the `Notifier` ([`notify.py`](../src/notify.py)) — Telegram
when configured, otherwise a no-op — and are formatted by `checkpoint_text`.
They are best-effort: a notifier exception is noted, never fatal.

## Re-runs

Rejecting a run replays only as much as needed. The deterministic planner in
[`controller.py`](../src/rerun/controller.py) maps a `RerunRequest` to a
`RerunPlan` with no LLM, network or media tooling. Four **scopes** decide how far
back to go:

| Scope | First replayed stage | Stages reused |
|---|---|---|
| `new_topic` | `trend` | none — discover a brand-new topic and replay everything |
| `full` | `angle` | `trend` — keep the topic, replay from the angle onwards |
| `assets` | `visuals` | through `voice` — keep the script and audio, regenerate visuals/motion/assembly/Short |
| `scenes` | `visuals` | through `voice` — like `assets`, limited to the given `scene_indices` |

`stages_to_run` is the ordered suffix of `STAGE_ORDER` beginning at the scope's
first stage, and `stages_reused` is the prefix before it; together they partition
`STAGE_ORDER` with no gaps or duplicates. `scenes` carries its `scene_indices`
into the plan; requested with an empty list it does not raise, but records a note
and degrades to `assets` behaviour.

Every re-run is **versioned**: attempts are 1-based and each attempt writes to
its own `attempt-<n>` directory under `base/run_id/`, so distinct attempt numbers
always map to distinct directories and an earlier attempt is never clobbered.
`attempt_dir` only *builds* the path (it never creates or overwrites), and
`existing_attempts` reads the run directory to report which attempts already
exist so the next number can be chosen. Escalate quality repairs
`scenes` → `assets` → `full` → `new_topic`.

## Free-tier deployment

Compute is split across free tiers so no local GPU/CPU is required:

| Plane | Host | Runs |
|---|---|---|
| Brain | **GitHub Actions** | Python + `ffmpeg`, all stage agents, TTS, assembly, publish, SQLite store |
| GPU hero clips (optional) | **Kaggle** or **Google Colab** (free GPU) | `notebooks/hero_render.ipynb` |
| Media APIs | Pollinations · Stable Horde · Pexels · Pixabay | images and stock clips |
| Scheduler / CI | **GitHub Actions** | daily dispatch and CI |
| Alerts / preview | Telegram + the run zip | checkpoint alerts and preview |

The host and the optional GPU worker never talk directly: they exchange JSON
job/result files through a shared folder, using the contract in
[`render_job.py`](../src/visuals/render_job.py). Full setup — the no-card
GitHub Actions host, the secrets matrix, the optional Kaggle/Colab step, and
scheduling — is in [`deploy.md`](deploy.md). The scheduled daily run is defined
by the GitHub Actions workflow
[`../.github/workflows/daily.yml`](../.github/workflows/daily.yml)
(01:30 UTC = 07:00 IST, with a manual `workflow_dispatch` for one category); the
bounded `--demo` mode for producing a first real video is described in
[`demo.md`](demo.md).
