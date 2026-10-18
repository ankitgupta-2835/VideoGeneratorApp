"""Free stock-photo search clients (Pexels + Pixabay).

Both providers expose a JSON search endpoint that returns photo metadata with
preview and full-resolution URLs. :class:`StockAsset` normalizes the two
response shapes into one record so downstream code can treat them alike, and
:func:`download` fetches an asset's bytes to disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.errors import ProviderError
from src.http_client import HttpClient

__all__ = ["PexelsClient", "PixabayClient", "StockAsset", "download"]


class StockAsset(BaseModel):
    """A single stock photo, normalized across providers."""

    id: str
    provider: str
    preview_url: str
    download_url: str
    width: int | None = None
    height: int | None = None


def _require_api_key(api_key: str, provider: str) -> str:
    """Return a stripped key, or raise if it is empty/blank."""
    key = api_key.strip()
    if not key:
        raise ProviderError(f"{provider} api key is empty")
    return key


class PexelsClient:
    BASE = "https://api.pexels.com/v1"

    def __init__(self, http: HttpClient, api_key: str) -> None:
        self._http = http
        self._api_key = api_key

    def search(
        self, query: str, *, per_page: int = 5, orientation: str = "landscape"
    ) -> list[StockAsset]:
        key = _require_api_key(self._api_key, "pexels")
        data: dict[str, Any] = self._http.get_json(
            f"{self.BASE}/search",
            params={"query": query, "per_page": per_page, "orientation": orientation},
            headers={"Authorization": key},
        )
        assets: list[StockAsset] = []
        for photo in data.get("photos", []):
            src = photo.get("src", {})
            assets.append(
                StockAsset(
                    id=str(photo.get("id")),
                    provider="pexels",
                    preview_url=src.get("medium", ""),
                    download_url=src.get("original", ""),
                    width=photo.get("width"),
                    height=photo.get("height"),
                )
            )
        return assets


class PixabayClient:
    BASE = "https://pixabay.com/api/"

    def __init__(self, http: HttpClient, api_key: str) -> None:
        self._http = http
        self._api_key = api_key

    def search(
        self, query: str, *, per_page: int = 5, orientation: str = "horizontal"
    ) -> list[StockAsset]:
        key = _require_api_key(self._api_key, "pixabay")
        data: dict[str, Any] = self._http.get_json(
            f"{self.BASE}/",
            params={
                "key": key,
                "q": query,
                "per_page": per_page,
                "image_type": "photo",
                "orientation": orientation,
            },
        )
        assets: list[StockAsset] = []
        for hit in data.get("hits", []):
            assets.append(
                StockAsset(
                    id=str(hit.get("id")),
                    provider="pixabay",
                    preview_url=hit.get("previewURL", ""),
                    download_url=hit.get("largeImageURL", ""),
                    width=hit.get("imageWidth"),
                    height=hit.get("imageHeight"),
                )
            )
        return assets


def download(http: HttpClient, asset: StockAsset, dest: Path) -> Path:
    """Fetch ``asset`` bytes and write them to ``dest``; return the path."""
    data = http.get_bytes(asset.download_url)
    if not data:
        raise ProviderError(f"empty download body for {asset.provider} asset {asset.id}")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest
