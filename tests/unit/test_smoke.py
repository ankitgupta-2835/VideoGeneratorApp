"""Task 0.1 smoke tests: the package and its subpackages import cleanly."""

import importlib

import src

SUBPACKAGES = [
    "src.agents",
    "src.trends",
    "src.script",
    "src.audio",
    "src.visuals",
    "src.assemble",
    "src.qa",
    "src.rerun",
    "src.review",
    "src.publish",
    "src.store",
]


def test_package_has_version():
    assert src.__version__ == "0.1.0"


def test_subpackages_import():
    for name in SUBPACKAGES:
        assert importlib.import_module(name) is not None
