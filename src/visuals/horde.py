"""Stable Horde image-generation client (async submit + poll).

Stable Horde is a free, crowdsourced inference service. Image generation is
asynchronous: a prompt is submitted to ``/generate/async`` which returns a job
id, the job is polled via ``/generate/check/{id}`` until it reports ``done``,
and the result URLs are then retrieved from ``/generate/status/{id}``.

Both the sleeper and the underlying HTTP client are injectable so tests run
without real delays or network access.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from src.errors import ProviderError
from src.http_client import HttpClient

__all__ = ["HordeClient"]


class HordeClient:
    BASE = "https://aihorde.net/api/v2"

    def __init__(
        self,
        http: HttpClient,
        *,
        api_key: str = "0000000000",
        sleep: Callable[[float], None] = time.sleep,
        poll_interval: float = 2.0,
        max_polls: int = 60,
    ) -> None:
        self._http = http
        self._api_key = api_key
        self._sleep = sleep
        self._poll_interval = poll_interval
        self._max_polls = max_polls

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def submit(
        self,
        prompt: str,
        *,
        width: int = 1280,
        height: int = 720,
        model: str = "stable_diffusion",
        steps: int = 30,
    ) -> str:
        """Submit a job and return its id."""
        payload = {
            "prompt": prompt,
            "params": {
                "width": width,
                "height": height,
                "steps": steps,
                "n": 1,
            },
            "models": [model],
        }
        data = self._http.post_json(
            f"{self.BASE}/generate/async",
            json_body=payload,
            headers={"apikey": self._api_key},
        )
        return data["id"]

    def check(self, job_id: str) -> dict:
        """Return the raw ``/generate/check`` status document for a job."""
        return self._http.get_json(f"{self.BASE}/generate/check/{job_id}")

    def fetch_result(self, job_id: str) -> list[str]:
        """Return the image URLs produced by a completed job."""
        data = self._http.get_json(f"{self.BASE}/generate/status/{job_id}")
        return [gen["img"] for gen in data["generations"]]

    def generate(self, prompt: str, out_path: Path, **kw: object) -> Path:
        """Submit a job, poll until done, download the first image, return its path."""
        job_id = self.submit(prompt, **kw)  # type: ignore[arg-type]

        for attempt in range(self._max_polls):
            status = self.check(job_id)
            if status.get("faulted"):
                raise ProviderError(f"horde job {job_id} faulted")
            if status.get("done"):
                urls = self.fetch_result(job_id)
                if not urls:
                    raise ProviderError(f"horde job {job_id} produced no images")
                out_path = Path(out_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(self._http.get_bytes(urls[0]))
                return out_path
            # Only wait if another poll is still coming.
            if attempt < self._max_polls - 1:
                self._sleep(self._poll_interval)

        raise ProviderError("horde job timed out")
