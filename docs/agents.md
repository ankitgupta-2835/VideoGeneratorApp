# Build-time agent roster

Every implementation task in this repository is executed by a **named build-time agent** — an
OpenCode subagent with a fixed identity, a stated specialty, and its own isolated git worktree.
Naming them makes their work **scrutable**: each commit and pull request records *which agent*
produced it, so a change can be traced back to a specific owner, reviewed against that owner's
scope, and held to a consistent standard over time.

> This file covers **build-time** agents (the engineers who write this repo). The **runtime**
> agents that the finished product runs are a different, larger roster — see
> `video-generator-app-workflow.md` §4A.

## Identity conventions

- **Commit trailer** — every task commit ends with:

  ```
  Task: <task-id>            # e.g. 2.1
  Agent: <Name> (<domain>)   # e.g. Pythia (trend discovery)
  ```

- **Pull request** — the body opens with `**Agent:** <Name> — <domain>`, and the title is
  `task <id>: <summary>`.
- **Reporting** — the Conductor reports results *per agent*, so a regression can be attributed
  to the owner that introduced it.
- **One agent, one worktree, one branch** — agents never share a checkout; the Conductor reviews
  each diff, runs CI, and merges centrally (the only serialized step).

## Observability (watching an agent work)

Background subagents only return their full report when they finish, so their activity is made
observable two ways:

1. **Progress journal (live).** Each agent appends timestamped, one-line entries to an
   append-only journal *outside* the repo (never committed):

   ```
   /tmp/opencode/journals/<agent>-<task>.log
   ```

   The Conductor relays `tail` snapshots so progress is visible while the work is in flight.

2. **Worktree snapshot (on demand).** Because an agent works in an isolated worktree, its state
   is directly inspectable at any moment:

   ```bash
   git -C /tmp/opencode/wt/<task> status --short    # files created/changed so far
   git -C /tmp/opencode/wt/<task> diff --stat       # size of the change so far
   tail /tmp/opencode/journals/<agent>-<task>.log   # the agent's own log
   ```

   A clean tree with a single signed commit means the agent finished and staged only what it
   intended.

## The roster

| Name | Domain | Owns | Example tasks |
|---|---|---|---|
| **Conductor** | Orchestration | Plan, split, review diffs, run CI, merge, report | all coordination |
| **Atlas** | Platform / infrastructure | Scaffold, CI, config, secrets, errors & logging, SQLite store, shared data contracts | 0.1–0.6, 2.4 |
| **Hermes** | Integrations | HTTP client (retry/cache), LLM client, notifier | 1.1–1.4 |
| **Pythia** | Trend discovery | Google Trends, Reddit, Hacker News, News RSS, YouTube; `trend_scout` agent | 1.5–1.9, 2.1 |
| **Argus** | Signals / scoring | Scorer + dedup, retention/CTR weighting (`analyst`) | 1.10, 6.x |
| **Melete** | Ideation / research | `angle_strategist`, `research` | 2.2, 2.3 |
| **Calliope** | Narrative / script | Blueprint authoring: `scriptwriter`, `script_director` | 2.5, 2.7 |
| **Polyhymnia** | Localization | Hindi `localizer`, bilingual timing parity | 2.6 |
| **Sentinel** | Trust & safety | `compliance` gate, `qa_critic` | 2.8, 4.x |
| **Orpheus** | Audio / TTS | `voice_director`, TTS backends, word/scene timestamps | 3.1 |
| **Pygmalion** | Visuals / image generation | Pollinations, Stable Horde, stock images (Pexels/Pixabay) | 3.3–3.5 |
| **Daedalus** | Media / assembly | Captions, motion, FFmpeg assembly, `visual_director`, Short derivation | 3.2, 3.6, 3.9–3.11 |
| **Icarus** | Hero video / GPU | Hero-video cascade, Colab render job | 3.7, 3.8 |
| **Janus** | Publishing / SEO | `seo`, `publisher`, checkpoint alerts | 4.x |
| **Vesta** | Revision | `revision_director`, re-run/escalation policy | 2C |

**Conductor** is the coordinating assistant (the main session). The specialists above are the
subagents it spawns. A specialist may own several tasks over time — that persistence is the
point: the same identity is accountable for its whole domain.

## Assignment ledger

A running record of who built what, for auditing. Newest first.

| Task | Agent | PR | Status |
|---|---|---|---|
| 3.11 `short_deriver` (9:16) | Daedalus | #39 | ✅ |
| 3.9 `visual_director` | Daedalus | #38 | ✅ |
| 3.10 FFmpeg assembly | Daedalus | #37 | ✅ |
| 3.8 Colab render job | Icarus | #36 | ✅ |
| 3.5 stock client | Pygmalion | #35 | ✅ |
| 1.15 CI ffmpeg fix | Atlas | #34 | ✅ |
| 3.7 hero video cascade | Icarus | #33 | ✅ |
| 3.6 motion (FFmpeg) | Daedalus | #32 | ✅ |
| 3.4 Stable Horde client | Pygmalion | #31 | ✅ |
| 3.3 Pollinations images | Pygmalion | #30 | ✅ |
| 3.2 captions (SRT/ASS) | Daedalus | #29 | ✅ |
| 3.1 `voice_director` + TTS | Orpheus | #28 | ✅ |
| 1.14 Media roster | Atlas | #27 | ✅ |
| 2.6 `localizer` | Polyhymnia | #25 | ✅ |
| 2.7 `script_director` | Calliope | #24 | ✅ |
| 2.3 `research` + factcheck | Melete | #23 | ✅ |
| 2.8 `compliance` | Sentinel | #22 | ✅ |
| 2.5 `scriptwriter` | Calliope | #21 | ✅ |
| 2.2 `angle_strategist` | Melete | #20 | ✅ |
| 2.4 Blueprint schema + validator | Atlas | #18 | ✅ |
| 2.1 `trend_scout` | Pythia | #17 | ✅ |
| 1.12 Observability conventions | Atlas | #19 | ✅ |
| 1.11 Agent roster | Atlas | #16 | ✅ |
| 1.8 News RSS | Pythia | #15 | ✅ |
| 1.9 YouTube mostPopular | Pythia | #13 | ✅ |
| 1.10 Scorer + dedup | Argus | #14 | ✅ |

*(Tasks before 1.8 predate the roster and were built directly by the Conductor.)*
