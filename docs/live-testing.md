# Live testing

The suite under `tests/live/` talks to **real external services**: trend
sources, the LLM providers, and the image generators. Those tests are
**opt-in and never run in CI**.

## Why they are off by default

`pyproject.toml` declares a `live` marker but the default `addopts` only
contain `-q`, so the marker alone does *not* filter anything -- a `live` test
would happily run and hit the network in CI. To close that gap without editing
`pyproject.toml`, `tests/live/conftest.py` gates the suite two ways:

- an **autouse fixture** that skips every live test unless `RUN_LIVE=1`; and
- a **`pytest_collection_modifyitems` hook** that deselects every item under
  `tests/live/` unless `RUN_LIVE=1`.

The net effect: a plain `pytest` collects **zero** live tests, so no accidental
network call can happen on a laptop or in CI.

## Running the live tests

```bash
# run everything under tests/live/
RUN_LIVE=1 pytest -m live tests/live

# a single provider
RUN_LIVE=1 pytest tests/live/test_providers_live.py -k reddit
```

`-m live` is a convenience filter (every module sets `pytestmark =
pytest.mark.live`); the `RUN_LIVE=1` gate is what actually enables execution.
Without `RUN_LIVE=1` the tests are deselected and report nothing collected.

## Keys and environment variables

Keys are read from the process environment (optionally via a local `.env`, as
described in `.env.example`) and are **never** hard-coded. Tests whose key is
missing are skipped with `pytest.mark.skipif`.

| Test(s) | Environment variable | Notes |
| --- | --- | --- |
| `test_llm_client_answers_json` | `LLM_PROVIDER` + the matching key: `GEMINI_API_KEY` / `GROQ_API_KEY` / `OPENROUTER_API_KEY` | Defaults to `gemini` when `LLM_PROVIDER` is unset. |
| `test_youtube_popular_live` | `YOUTUBE_API_KEY` | YouTube Data API v3 key. |
| `test_pexels_search_live` | `PEXELS_API_KEY` | Free Pexels API key. |
| `test_pixabay_search_live` | `PIXABAY_API_KEY` | Free Pixabay API key. |
| `test_google_trends_live`, `test_reddit_live`, `test_hackernews_live`, `test_news_rss_live`, `test_pollinations_generates_file`, `test_horde_submits_job` | *(none)* | Keyless public/free endpoints. |

## Cost and rate-limit warning

These clients deliberately target **free tiers**, and free tiers are volatile:

- **Rate limits.** Google Trends, Reddit, Hacker News and News RSS throttle
  aggressively; Reddit in particular returns `429`/`403` for default clients.
  Keep `limit`/`per_page` small.
- **LLM quotas.** Gemini, Groq and OpenRouter free tiers cap requests/minute
  and tokens/day. A single smoke request is intentional; do not loop.
- **Image generation.** Pollinations is best-effort and can be slow or return
  placeholder output. Stable Horde is a crowdsourced queue -- anonymous jobs
  can wait **minutes**; the live test therefore stops after a successful job
  submission instead of polling to completion.
- **Stock APIs.** Pexels and Pixabay free tiers are limited to a few hundred
  requests/hour.

Because of this, live assertions are intentionally minimal (a non-empty list,
a non-empty file, a returned job id). A live failure often means "the free
service was busy", not "the client is broken". Re-run before investigating.

## CI

CI runs plain `pytest`. With `RUN_LIVE` unset the hook deselects `tests/live/`
entirely, so the pipeline never depends on a network service or a secret.
