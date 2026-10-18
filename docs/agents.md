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
| **Daedalus** | Media | `voice_director`, `visual_director`, `editor`, Short derivation | 3.x |
| **Janus** | Publishing / SEO | `seo`, `publisher`, checkpoint alerts | 4.x |
| **Vesta** | Revision | `revision_director`, re-run/escalation policy | 2C |

**Conductor** is the coordinating assistant (the main session). The specialists above are the
subagents it spawns. A specialist may own several tasks over time — that persistence is the
point: the same identity is accountable for its whole domain.

## Assignment ledger

A running record of who built what, for auditing.

| Task | Agent | PR | Status |
|---|---|---|---|
| 1.11 | Atlas | #16 | ✅ |
| 1.12 | Atlas | — | this section |
| 2.1 | Pythia | #17 | ✅ |
| 2.4 | Atlas | #18 | ✅ |
| 1.8 | Pythia | #15 | ✅ |
| 1.9 | Pythia | #13 | ✅ |
| 1.10 | Argus | #14 | ✅ |

*(Earlier Phase 0/1 tasks predate the roster and were built directly by the Conductor.)*
