"""Task 4.3 tests: the side-by-side attempt preview page."""

from __future__ import annotations

from pathlib import Path

from src.review.build_review_page import Attempt, build_review_page

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "golden" / "review"

# A fixed fixture shared by the golden-file test so it is reproducible
# byte-for-byte. It deliberately covers a scored long+short attempt and an
# unscored long-only attempt.
GOLDEN_ATTEMPTS = [
    Attempt(
        run_id="run-002",
        attempt_no=2,
        category="science",
        title="Why the sky is blue",
        video_path="videos/run-002/attempt-2.mp4",
        short_path="videos/run-002/attempt-2-short.mp4",
        score=8.5,
        status="approved",
        notes="Tight pacing; strong hook.",
    ),
    Attempt(
        run_id="run-001",
        attempt_no=1,
        category="history",
        title="The fall of Rome",
        video_path="videos/run-001/attempt-1.mp4",
        score=None,
        status="pending",
    ),
]


def _render(tmp_path: Path, attempts: list[Attempt]) -> str:
    out = build_review_page(attempts, tmp_path / "review.html")
    assert out.exists()
    return out.read_text(encoding="utf-8")


def test_one_card_per_attempt(tmp_path: Path) -> None:
    html = _render(tmp_path, GOLDEN_ATTEMPTS)
    assert html.count('class="card"') == len(GOLDEN_ATTEMPTS)


def test_long_and_short_videos_have_expected_src(tmp_path: Path) -> None:
    html = _render(tmp_path, GOLDEN_ATTEMPTS)
    # Two attempts in, two out: attempt 1 has a long only, attempt 2 has both.
    assert html.count("<video") == 3
    assert 'src="videos/run-002/attempt-2.mp4"' in html
    assert 'src="videos/run-002/attempt-2-short.mp4"' in html
    assert 'src="videos/run-001/attempt-1.mp4"' in html


def test_long_only_attempt_has_no_short_video(tmp_path: Path) -> None:
    html = _render(
        tmp_path,
        [
            Attempt(
                run_id="run-003",
                attempt_no=3,
                category="tech",
                title="Long only",
                video_path="videos/run-003/attempt-3.mp4",
            )
        ],
    )
    assert html.count("<video") == 1


def test_attempts_ordered_by_attempt_no(tmp_path: Path) -> None:
    attempts = [
        Attempt(
            run_id="b",
            attempt_no=9,
            category="c",
            title="Ninth",
            video_path="v/9.mp4",
        ),
        Attempt(
            run_id="a",
            attempt_no=2,
            category="c",
            title="Second",
            video_path="v/2.mp4",
        ),
        Attempt(
            run_id="z",
            attempt_no=5,
            category="c",
            title="Fifth",
            video_path="v/5.mp4",
        ),
    ]
    html = _render(tmp_path, attempts)
    assert html.index("Ninth") > html.index("Fifth") > html.index("Second")
    # Same attempt_no ties break on run_id for a stable order.
    assert html.index("Second") < html.index("Fifth")


def test_title_script_tag_is_escaped(tmp_path: Path) -> None:
    html = _render(
        tmp_path,
        [
            Attempt(
                run_id="run-x",
                attempt_no=1,
                category="misc",
                title="<script>alert(1)</script>",
                video_path="v/x.mp4",
                notes="<b>bold</b>",
            )
        ],
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<b>bold</b>" not in html
    assert "&lt;b&gt;bold&lt;/b&gt;" in html


def test_empty_attempts_creates_page(tmp_path: Path) -> None:
    html = _render(tmp_path, [])
    assert html.count('class="card"') == 0
    assert "No attempts to review." in html


def test_matches_golden(tmp_path: Path) -> None:
    expected = (GOLDEN_DIR / "sample.html").read_text(encoding="utf-8")
    rendered = build_review_page(
        list(GOLDEN_ATTEMPTS),
        tmp_path / "sample.html",
    ).read_text(encoding="utf-8")
    assert rendered == expected
