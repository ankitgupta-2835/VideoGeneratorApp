"""Preview page: a self-contained HTML review sheet of video attempts.

The reviewer needs to compare several generated attempts side by side. This
module renders a list of :class:`Attempt` records into a single HTML document
with inline CSS and no external assets, so it can be opened straight from disk
(or served) with nothing else installed.

Every piece of dynamic text and every attribute value is HTML-escaped, and the
output contains no timestamps, so a fixed fixture reproduces a byte-for-byte
golden file.
"""

from __future__ import annotations

import html
from pathlib import Path

from pydantic import BaseModel

__all__ = ["Attempt", "build_review_page"]

_CSS = """\
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 1.5rem;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  background: #f5f6f8;
  color: #1b1f24;
}
h1 { font-size: 1.5rem; margin: 0 0 1rem; }
.cards { display: flex; flex-wrap: wrap; gap: 1.25rem; }
.card {
  flex: 1 1 420px;
  max-width: 640px;
  background: #ffffff;
  border: 1px solid #d7dbe0;
  border-radius: 10px;
  padding: 1rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}
.card h2 { font-size: 1.15rem; margin: 0 0 0.5rem; }
.meta { display: flex; flex-wrap: wrap; gap: 0.5rem 1rem; margin: 0 0 0.75rem; }
.meta dt { font-weight: 600; color: #57606a; }
.meta dd { margin: 0; }
.meta > div { display: flex; gap: 0.35rem; }
.status { text-transform: capitalize; }
.notes { margin: 0 0 0.75rem; white-space: pre-wrap; }
video { display: block; width: 100%; margin-top: 0.5rem; background: #000; border-radius: 6px; }
.label { font-size: 0.8rem; font-weight: 600; color: #57606a; margin-top: 0.75rem; }
.empty { color: #57606a; }
"""


class Attempt(BaseModel):
    """One generated video attempt to be reviewed."""

    run_id: str
    attempt_no: int
    category: str
    title: str
    video_path: str
    short_path: str | None = None
    score: float | None = None
    status: str = "pending"  # pending | approved | rejected
    notes: str = ""


def _esc(value: object) -> str:
    """Escape ``value`` for use in text or a double-quoted attribute."""

    return html.escape(str(value), quote=True)


def _format_score(score: float | None) -> str:
    return "—" if score is None else f"{score:.2f}"


def _render_video(src: str) -> str:
    return (
        '<video controls preload="metadata">'
        f'<source src="{_esc(src)}" type="video/mp4">'
        f"Your browser does not support the video tag ({_esc(src)})."
        "</video>"
    )


def _render_card(attempt: Attempt) -> str:
    parts = [
        '<article class="card">',
        f"<h2>{_esc(attempt.title)}</h2>",
        '<dl class="meta">',
        f"<div><dt>Category</dt><dd>{_esc(attempt.category)}</dd></div>",
        f"<div><dt>Run</dt><dd>{_esc(attempt.run_id)} #{attempt.attempt_no}</dd></div>",
        f"<div><dt>Score</dt><dd>{_esc(_format_score(attempt.score))}</dd></div>",
        f'<div><dt>Status</dt><dd class="status">{_esc(attempt.status)}</dd></div>',
        "</dl>",
        f'<p class="notes">{_esc(attempt.notes)}</p>',
        '<div class="label">Long video</div>',
        _render_video(attempt.video_path),
    ]
    if attempt.short_path is not None:
        parts.append('<div class="label">Short video</div>')
        parts.append(_render_video(attempt.short_path))
    parts.append("</article>")
    return "\n".join(parts)


def build_review_page(
    attempts: list[Attempt],
    out_path: Path,
    *,
    title: str = "Video attempts",
) -> Path:
    """Render ``attempts`` into a self-contained HTML page at ``out_path``.

    Attempts are ordered by ``attempt_no`` then ``run_id``. Dynamic text is
    HTML-escaped. Parent directories are created and the path is returned.
    """

    ordered = sorted(attempts, key=lambda a: (a.attempt_no, a.run_id))
    cards = "\n".join(_render_card(a) for a in ordered)
    if not cards:
        cards = '<p class="empty">No attempts to review.</p>'

    document = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_esc(title)}</title>\n"
        f"<style>\n{_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"<h1>{_esc(title)}</h1>\n"
        f'<div class="cards">\n{cards}\n</div>\n'
        "</body>\n"
        "</html>\n"
    )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(document, encoding="utf-8")
    return out_path
