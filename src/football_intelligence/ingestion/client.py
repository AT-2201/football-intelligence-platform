import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx


class StatsBombOpenDataClient:
    """Downloads provider JSON and keeps a local, replayable cache."""

    def __init__(self, base_url: str, cache_dir: Path, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir
        self.timeout = timeout

    def get_json(self, relative_path: str, *, force: bool = False) -> Any:
        cache_path = self.cache_dir / relative_path
        if cache_path.exists() and not force:
            return json.loads(cache_path.read_text(encoding="utf-8"))

        response = httpx.get(f"{self.base_url}/{relative_path}", timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload

    def competitions(self, *, force: bool = False) -> list[dict[str, Any]]:
        return self.get_json("competitions.json", force=force)

    def matches(
        self, competition_id: int, season_id: int, *, force: bool = False
    ) -> list[dict[str, Any]]:
        return self.get_json(f"matches/{competition_id}/{season_id}.json", force=force)

    def lineups(self, match_id: int, *, force: bool = False) -> list[dict[str, Any]]:
        return self.get_json(f"lineups/{match_id}.json", force=force)

    def events(self, match_id: int, *, force: bool = False) -> list[dict[str, Any]]:
        return self.get_json(f"events/{match_id}.json", force=force)

    def prefetch_matches(
        self,
        match_ids: list[int],
        *,
        force: bool = False,
        workers: int = 4,
    ) -> None:
        """Download match payloads concurrently; normalization remains transactional."""
        paths = [
            path
            for match_id in match_ids
            for path in (f"lineups/{match_id}.json", f"events/{match_id}.json")
        ]

        def fetch(path: str) -> None:
            self.get_json(path, force=force)

        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            for _ in executor.map(fetch, paths):
                pass
