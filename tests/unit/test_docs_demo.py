"""Task 6.1 / 5.26 tests: the demo quickstart doc.

These keep ``docs/demo.md`` honest and in sync with the frozen CLI contract and
the deployment reality:

* the doc exists and documents ``--demo`` / ``--max-scenes``;
* it names the no-card GitHub Actions host, ``.env`` and a free LLM key;
* it lists all four rotating categories, including ``general_knowledge``;
* every relative local link resolves from the repo root;
* ``README.md`` points at the demo flags.

No network access is required.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_DOC = REPO_ROOT / "docs" / "demo.md"
README = REPO_ROOT / "README.md"

CATEGORIES = ["ai_tech", "finance", "health_fitness", "general_knowledge"]

#: Markdown inline links: ``[text](target)``. We keep the target only.
_LINK_RE = re.compile(r"\]\(([^)]+)\)")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_demo_doc_exists():
    assert DEMO_DOC.is_file(), f"missing {DEMO_DOC}"


def test_demo_doc_documents_flags():
    text = _text(DEMO_DOC)
    for needle in ("--demo", "--max-scenes", "--dry-run", "--category"):
        assert needle in text, f"docs/demo.md is missing {needle!r}"


def test_demo_doc_names_the_host_and_env():
    text = _text(DEMO_DOC)
    assert "GitHub Actions" in text, "demo doc does not mention the no-card host"
    assert "no card" in text.lower() or "no-card" in text.lower(), "demo doc does not say no card"
    assert ".env" in text, "demo doc does not mention .env"
    assert ".env.example" in text, "demo doc does not point at .env.example"


def test_demo_doc_names_free_llm_key_options():
    text = _text(DEMO_DOC)
    # At least one concrete free-provider key must be named, and the doc must
    # say the key is free.
    assert "LLM_PROVIDER" in text, "demo doc does not explain LLM_PROVIDER"
    key_names = ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY")
    assert any(name in text for name in key_names), "demo doc names no LLM provider key"
    lowered = text.lower()
    assert "free" in lowered and (
        "llm key" in lowered or "free llm" in lowered
    ), "demo doc does not describe the free LLM key"


def test_demo_doc_lists_all_categories():
    text = _text(DEMO_DOC)
    for category in CATEGORIES:
        assert category in text, f"docs/demo.md does not mention category {category!r}"
    assert "general_knowledge" in text, "demo doc must show the general_knowledge key"


def test_demo_doc_links_resolve():
    missing: list[str] = []
    for target in (m.group(1).strip() for m in _LINK_RE.finditer(_text(DEMO_DOC))):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        file_part = target.split("#", 1)[0]
        if not file_part:
            continue
        candidates = [DEMO_DOC.parent / file_part, REPO_ROOT / file_part]
        if not any(candidate.exists() for candidate in candidates):
            missing.append(target)
    assert not missing, f"docs/demo.md has broken local links: {missing}"


def test_readme_mentions_demo_flag():
    text = _text(README)
    assert "--demo" in text, "README does not mention --demo"
    assert "--max-scenes" in text, "README does not mention --max-scenes"
