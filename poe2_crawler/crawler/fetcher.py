"""Async HTML fetcher with caching, rate-limiting, and retry."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from pathlib import Path

import aiohttp
import yaml

logger = logging.getLogger(__name__)

with open("config/settings.yaml") as f:
    _settings = yaml.safe_load(f)


class RateLimiter:
    def __init__(self, rps: float = 1.0):
        self._interval = 1.0 / rps
        self._last = 0.0

    async def wait(self):
        now = time.monotonic()
        wait = self._last + self._interval - now
        if wait > 0:
            await asyncio.sleep(wait)
        self._last = time.monotonic()


class Fetcher:
    def __init__(self, cache_dir: str = "data/cache", cache_enabled: bool = True):
        self._session: aiohttp.ClientSession | None = None
        self._limiter = RateLimiter(rps=_settings["rate_limit_rps"])
        self._cache_dir = Path(cache_dir)
        self._cache_enabled = cache_enabled
        self._ua = _settings["user_agent"]
        self._timeout = _settings["request_timeout_sec"]
        self._retry_max = _settings["retry_max"]
        if cache_enabled:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    async def _session_get(self):
        if self._session is None:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": self._ua},
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            )
        return self._session

    def _cache_path(self, url: str) -> Path:
        h = hashlib.md5(url.encode()).hexdigest()[:16]
        return self._cache_dir / f"{h}.html"

    async def fetch(self, url: str) -> str | None:
        cache_path = self._cache_path(url)
        if self._cache_enabled and cache_path.exists():
            return cache_path.read_text(encoding="utf-8", errors="replace")

        await self._limiter.wait()

        for attempt in range(self._retry_max):
            try:
                session = await self._session_get()
                async with session.get(url) as resp:
                    if resp.status == 200:
                        html = await resp.text(encoding="utf-8", errors="replace")
                        if self._cache_enabled:
                            cache_path.write_text(html, encoding="utf-8")
                        return html
                    elif resp.status == 404:
                        logger.warning("404: %s", url)
                        return None
                    elif resp.status == 429:
                        retry_after = int(resp.headers.get("Retry-After", 10))
                        logger.info("429, waiting %ds", retry_after)
                        await asyncio.sleep(retry_after)
                    else:
                        logger.warning("%d on %s (attempt %d)", resp.status, url, attempt + 1)
            except Exception as e:
                logger.warning("fetch error %s (attempt %d): %s", url, attempt + 1, e)
            await asyncio.sleep(_settings["retry_backoff_sec"] * (attempt + 1))
        return None

    async def close(self):
        if self._session:
            await self._session.close()
