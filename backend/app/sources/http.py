"""Shared HTTP client: per-host rate limiting, retries, and an on-disk JSON cache.

Historical F1 data is immutable, so responses are cached permanently unless a TTL is given.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

import httpx
import pandas as pd

from app.config import HTTP_TIMEOUT_S, RATE_LIMITS, RAW_CACHE_DIR

log = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window limiter supporting several (count, window) rules at once."""

    def __init__(self, rules: list[tuple[int, float]]):
        self.rules = rules
        self.history: deque[float] = deque()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        longest = max((w for _, w in self.rules), default=0)
        while True:
            with self.lock:
                now = time.monotonic()
                while self.history and now - self.history[0] > longest:
                    self.history.popleft()
                wait = 0.0
                for count, window in self.rules:
                    recent = [t for t in self.history if now - t < window]
                    if len(recent) >= count:
                        wait = max(wait, window - (now - recent[-count]))
                if wait <= 0:
                    self.history.append(now)
                    return
            time.sleep(wait + 0.01)


class NotFound(Exception):
    """The source has no data for this query (e.g. OpenF1 'No results found')."""


class HttpClient:
    def __init__(self) -> None:
        self._client = httpx.Client(timeout=HTTP_TIMEOUT_S, follow_redirects=True)
        self._limiters = {host: RateLimiter(rules) for host, rules in RATE_LIMITS.items()}

    @staticmethod
    def _url(base: str, params: dict | None) -> str:
        if not params:
            return base
        # OpenF1 uses operators inside the key (e.g. "date>"), so keys are passed through verbatim.
        return f"{base}?{urlencode(params, safe='<>:=')}"

    def _cache_path(self, url: str, suffix: str):
        host = urlsplit(url).hostname or "unknown"
        digest = hashlib.sha1(url.encode()).hexdigest()
        return RAW_CACHE_DIR / host / f"{digest}.{suffix}"

    def _fetch(self, url: str, headers: dict | None) -> httpx.Response:
        host = urlsplit(url).hostname or ""
        limiter = self._limiters.get(host)
        for attempt in range(5):
            if limiter:
                limiter.acquire()
            resp = self._client.get(url, headers=headers)
            if resp.status_code == 429 or resp.status_code >= 500:
                delay = float(resp.headers.get("Retry-After", 2 ** attempt))
                log.warning("HTTP %s from %s, retrying in %.1fs", resp.status_code, host, delay)
                time.sleep(delay)
                continue
            return resp
        resp.raise_for_status()
        return resp

    def get_json(
        self,
        base: str,
        params: dict | None = None,
        *,
        ttl: timedelta | None = None,
        cache: bool = True,
        headers: dict | None = None,
    ):
        """GET JSON. `ttl=None` caches forever. Raises NotFound for empty OpenF1 results / 404."""
        url = self._url(base, params)
        path = self._cache_path(url, "json")
        if cache and path.exists():
            age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if ttl is None or age < ttl:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("__not_found__") if isinstance(payload, dict) else False:
                    raise NotFound(url)
                return payload

        resp = self._fetch(url, headers)
        not_found = resp.status_code == 404
        if not not_found:
            resp.raise_for_status()
        data = {"__not_found__": True} if not_found else resp.json()
        if cache:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        if not_found:
            raise NotFound(url)
        return data

    def get_csv(self, base: str, params: dict | None = None, headers: dict | None = None) -> pd.DataFrame:
        """GET CSV without raw caching (callers persist the result as Parquet)."""
        url = self._url(base, params)
        resp = self._fetch(url, headers)
        if resp.status_code == 404:
            raise NotFound(url)
        resp.raise_for_status()
        if not resp.text.strip():
            raise NotFound(url)
        return pd.read_csv(io.StringIO(resp.text))


http = HttpClient()
