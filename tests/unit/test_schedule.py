"""Task 5.4 tests: date -> category rotation helper."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.pipeline.schedule import ROTATION, category_for_date, main


def test_consecutive_days_cover_all_four_categories():
    start = date(2026, 1, 1)
    seen = {category_for_date(start + timedelta(days=i)) for i in range(len(ROTATION))}
    assert seen == set(ROTATION)


def test_same_day_is_stable():
    d = date(2026, 6, 15)
    assert category_for_date(d) == category_for_date(d)


def test_time_of_day_does_not_matter():
    # The helper takes a ``date`` (no time component), so two calls that refer
    # to the same calendar day are identical.
    d = date(2026, 3, 9)
    assert category_for_date(d) == category_for_date(date(2026, 3, 9))


def test_cycles_after_rotation_length():
    d = date(2026, 5, 20)
    assert category_for_date(d + timedelta(days=len(ROTATION))) == category_for_date(d)


def test_result_is_always_a_known_category():
    for i in range(400):
        assert category_for_date(date(2026, 1, 1) + timedelta(days=i)) in ROTATION


def test_empty_rotation_raises():
    with pytest.raises(ValueError):
        category_for_date(date(2026, 1, 1), [])


def test_custom_rotation_is_honoured():
    assert category_for_date(date(2026, 1, 1), ["only"]) == "only"


def test_main_prints_a_valid_category(capsys):
    assert main([]) == 0
    printed = capsys.readouterr().out.strip()
    assert printed in ROTATION


def test_main_resolves_an_explicit_date(capsys):
    assert main(["--date", "2026-01-01"]) == 0
    printed = capsys.readouterr().out.strip()
    assert printed == category_for_date(date(2026, 1, 1))
