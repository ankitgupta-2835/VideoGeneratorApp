"""Shared trend-source types and helpers."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

__all__ = ["TrendItem", "TrendSource", "matches_keywords", "parse_rss"]


class TrendItem(BaseModel):
    """A single candidate topic from a trend source."""

    title: str
    url: str | None = None
    source: str
    metrics: dict[str, float] = Field(default_factory=dict)
    published_at: str | None = None


def matches_keywords(text: str, keywords: list[str] | None) -> bool:
    """True if ``text`` contains any keyword (case-insensitive); True if no keywords."""
    if not keywords:
        return True
    lowered = text.lower()
    return any(k.lower() in lowered for k in keywords)


def parse_rss(xml_bytes: bytes) -> list[dict[str, str]]:
    """Extract ``{title, link}`` pairs from RSS/Atom payloads (namespace-agnostic)."""
    root = ET.fromstring(xml_bytes)
    results: list[dict[str, str]] = []
    for node in root.iter():
        if node.tag.split("}")[-1] != "item" and node.tag.split("}")[-1] != "entry":
            continue
        title = ""
        link = ""
        for child in node:
            tag = child.tag.split("}")[-1]
            if tag == "title" and child.text:
                title = child.text.strip()
            elif tag == "link":
                link = (child.text or child.attrib.get("href") or "").strip()
        if title:
            results.append({"title": title, "link": link})
    return results


class TrendSource(ABC):
    """A source of candidate topics."""

    name: str = "source"

    @abstractmethod
    def fetch(self, *, keywords: list[str] | None = None) -> list[TrendItem]:
        """Return candidate topics, optionally filtered to ``keywords``."""
