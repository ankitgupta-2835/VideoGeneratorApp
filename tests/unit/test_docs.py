"""Documentation drift checks.

These tests keep the public-facing docs honest and in sync with the code:

* ``README.md`` exists and covers the quickstart, CLI, tests and the doc set.
* The README names all four rotating categories and no longer leaks the
  private ``~/.opencode`` build-plan path.
* ``docs/architecture.md`` exists and mentions every pipeline stage and every
  re-run scope (iterated from the source of truth, so a new stage/scope fails
  the suite until it is documented).
* No relative local markdown link in the docs points at a missing file.
* ``docs/architecture.md`` has a table of contents.

No network access is required.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.rerun.controller import STAGE_ORDER, Scope

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
ARCHITECTURE = REPO_ROOT / "docs" / "architecture.md"

CATEGORIES = ["ai_tech", "finance", "health_fitness", "general_knowledge"]

#: Markdown inline links: ``[text](target)``. We keep the target only.
_LINK_RE = re.compile(r"\]\(([^)]+)\)")


def test_readme_exists_and_covers_quickstart():
    text = README.read_text(encoding="utf-8")
    assert README.is_file()
    for needle in (
        "python -m src.pipeline",
        "pip install -e",
        "pytest",
        "--dry-run",
        "docs/architecture.md",
        "docs/deploy.md",
        "docs/agents.md",
    ):
        assert needle in text, f"README is missing {needle!r}"


def test_readme_lists_all_categories():
    text = README.read_text(encoding="utf-8")
    for category in CATEGORIES:
        assert category in text, f"README does not mention category {category!r}"


def test_readme_has_no_private_plan_path():
    text = README.read_text(encoding="utf-8")
    assert "~/.opencode" not in text, "README still references the private ~/.opencode path"


def test_architecture_mentions_every_stage_and_scope():
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for stage in STAGE_ORDER:
        assert stage.value in text, f"architecture.md does not document stage {stage.value!r}"
    for scope in Scope:
        assert scope.value in text, f"architecture.md does not document scope {scope.value!r}"


def test_architecture_has_toc():
    text = ARCHITECTURE.read_text(encoding="utf-8")
    assert "## Table of Contents" in text
    # A ToC implies at least one anchor-style entry linking into the document.
    assert re.search(r"^\s*-\s*\[.+?\]\(#.+?\)", text, re.MULTILINE)


def _markdown_targets(path: Path) -> list[str]:
    return [m.group(1).strip() for m in _LINK_RE.finditer(path.read_text(encoding="utf-8"))]


@pytest.mark.parametrize("doc", [README, ARCHITECTURE], ids=["README", "architecture"])
def test_local_links_resolve(doc: Path):
    missing: list[str] = []
    for target in _markdown_targets(doc):
        if target.startswith(("http://", "https://", "mailto:", "#")) or target.startswith("#"):
            continue
        # Drop any ``#anchor`` fragment; only the file path must exist.
        file_part = target.split("#", 1)[0]
        if not file_part:
            continue
        # Relative links render relative to the document's own directory; also
        # accept root-relative links (resolved from the repo root).
        candidates = [doc.parent / file_part, REPO_ROOT / file_part]
        if not any(candidate.exists() for candidate in candidates):
            missing.append(target)
    assert not missing, f"{doc.name} has broken local links: {missing}"
