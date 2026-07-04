"""Currency pricing service for PoE2 currency exchange rates."""

import logging
import os
import time
from typing import Any

import httpx
from redis import Redis

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

# Official PoE currency exchange API
POE_EXCHANGE_API = "https://www.pathofexile.com/api/trade/exchange/{realm}"
CACHE_KEY = "pricing:rates:{realm}"
CACHE_TTL_SECONDS = 3600  # 1 hour
USER_AGENT = "PoE2LI/1.0"


class PricingService:
    """Service for fetching and caching PoE2 currency exchange rates."""

    def __init__(self, redis_client: Redis | None = None) -> None:
        self._redis = redis_client or get_redis()

    async def refresh_currency_rates(self, realm: str = "poe2") -> dict[str, Any]:
        """Fetch latest currency exchange rates from official API and cache in Redis.

        Implements exponential backoff on 429 responses.

        Args:
            realm: Game realm identifier, defaults to "poe2".

        Returns:
            Parsed exchange rate data from the API.

        Raises:
            RuntimeError: If the API request fails after all retries.
        """
        url = POE_EXCHANGE_API.format(realm=realm)
        headers = {"User-Agent": USER_AGENT}
        max_retries = 5
        base_delay = 1.0

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(max_retries):
                try:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()

                    # Cache the result
                    cache_key = CACHE_KEY.format(realm=realm)
                    self._redis.setex(
                        cache_key,
                        CACHE_TTL_SECONDS,
                        str(data),
                    )

                    logger.info(
                        "Currency rates refreshed for realm=%s (attempt %d)",
                        realm,
                        attempt + 1,
                    )
                    return data

                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if status == 429:
                        # Exponential backoff
                        retry_after = exc.response.headers.get("Retry-After")
                        if retry_after is not None:
                            try:
                                delay = float(retry_after)
                            except ValueError:
                                delay = base_delay * (2 ** attempt)
                        else:
                            delay = base_delay * (2 ** attempt)

                        logger.warning(
                            "Rate limited (429), retrying in %.1fs (attempt %d/%d)",
                            delay,
                            attempt + 1,
                            max_retries,
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "HTTP error %d fetching currency rates: %s",
                            status,
                            exc,
                        )
                        raise

                except (httpx.RequestError, httpx.TimeoutException) as exc:
                    logger.error(
                        "Request error fetching currency rates (attempt %d/%d): %s",
                        attempt + 1,
                        max_retries,
                        exc,
                    )
                    if attempt == max_retries - 1:
                        raise RuntimeError(
                            f"Failed to fetch currency rates after {max_retries} attempts"
                        ) from exc
                    time.sleep(base_delay * (2 ** attempt))

        raise RuntimeError(
            f"Failed to fetch currency rates for realm={realm} after {max_retries} attempts"
        )

    def get_chaos_equivalent(self, currency: str, amount: float = 1.0) -> float:
        """Calculate the chaos orb equivalent for a given currency and amount.

        Reads cached exchange rates from Redis.

        Args:
            currency: Currency identifier (e.g., "chaos", "divine", "exalted").
            amount: Amount of the currency.

        Returns:
            Chaos equivalent value. Returns 0.0 if no cached rates available.
        """
        cache_key = CACHE_KEY.format(realm="poe2")
        raw = self._redis.get(cache_key)

        if raw is None:
            logger.warning("No cached currency rates found; returning 0.0")
            return 0.0

        try:
            data = eval(raw) if isinstance(raw, str) else raw
        except Exception:
            logger.error("Failed to parse cached currency rates")
            return 0.0

        # The official API returns a nested structure with currency data
        # Adapt to the actual response shape; default to 1:1 for chaos
        rates = data.get("rates", data) if isinstance(data, dict) else {}
        currency_data = rates.get(currency.lower())

        if currency_data is None:
            logger.warning("Currency '%s' not found in cached rates", currency)
            return 0.0

        # Handle common response shapes
        if isinstance(currency_data, dict):
            chaos_equiv = currency_data.get("chaos_equivalent") or currency_data.get("value", 1.0)
        else:
            chaos_equiv = float(currency_data)

        return round(float(amount) * float(chaos_equiv), 4)

    def get_cached_rates(self, realm: str = "poe2") -> dict[str, Any] | None:
        """Return cached rates without hitting the API.

        Args:
            realm: Game realm identifier.

        Returns:
            Cached rate data dict, or None if not cached.
        """
        cache_key = CACHE_KEY.format(realm=realm)
        raw = self._redis.get(cache_key)
        if raw is None:
            return None
        try:
            return eval(raw) if isinstance(raw, str) else raw
        except Exception:
            return None
