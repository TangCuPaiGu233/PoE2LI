"""Unit tests for PricingService."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.pricing_service import PricingService


class _FakeHTTPStatusError(httpx.HTTPStatusError):
    """Minimal stand-in for httpx.HTTPStatusError."""

    def __init__(self, status_code: int, headers: dict) -> None:
        self.response = MagicMock()
        self.response.status_code = status_code
        self.response.headers = headers
        self.response.text = "error"
        super().__init__("error", request=None, response=self.response)


@pytest.fixture()
def mock_redis():
    """Mock Redis client."""
    redis = MagicMock()
    redis.get = MagicMock(return_value=None)
    redis.setex = MagicMock()
    return redis


@pytest.fixture()
def pricing_service(mock_redis):
    """PricingService with mocked Redis."""
    return PricingService(redis_client=mock_redis)


class TestRefreshCurrencyRates:
    """Tests for refresh_currency_rates."""

    @pytest.mark.asyncio
    async def test_refresh_success(self, pricing_service, mock_redis):
        """Successful API call stores rates in Redis."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"X-Rate-Limit-Remaining": "59"}
        mock_response.json.return_value = {"chaos": {"chaos_equivalent": 1.0}, "divine": {"chaos_equivalent": 150.0}}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.services.pricing_service.httpx.AsyncClient", return_value=mock_client):
            result = await pricing_service.refresh_currency_rates(realm="poe2")

        assert result == {"chaos": {"chaos_equivalent": 1.0}, "divine": {"chaos_equivalent": 150.0}}
        mock_redis.setex.assert_called_once()
        args, kwargs = mock_redis.setex.call_args
        assert args[0].startswith("pricing:rates:poe2")

    @pytest.mark.asyncio
    async def test_refresh_429_then_success(self, pricing_service, mock_redis):
        """429 response triggers exponential backoff, then succeeds."""
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.headers = {"Retry-After": "0.01"}
        mock_429.raise_for_status.side_effect = _FakeHTTPStatusError(429, {"Retry-After": "0.01"})

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.headers = {"X-Rate-Limit-Remaining": "59"}
        mock_200.json.return_value = {"chaos": {"chaos_equivalent": 1.0}}
        mock_200.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[mock_429, mock_200])

        with patch("app.services.pricing_service.httpx.AsyncClient", return_value=mock_client), \
             patch("app.services.pricing_service.time.sleep"):
            result = await pricing_service.refresh_currency_rates(realm="poe2")

        assert result == {"chaos": {"chaos_equivalent": 1.0}}

    @pytest.mark.asyncio
    async def test_refresh_429_no_retry_header(self, pricing_service, mock_redis):
        """429 without Retry-After uses exponential backoff."""
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.headers = {}
        mock_429.raise_for_status.side_effect = _FakeHTTPStatusError(429, {})

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.headers = {"X-Rate-Limit-Remaining": "59"}
        mock_200.json.return_value = {"chaos": {"chaos_equivalent": 1.0}}
        mock_200.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[mock_429, mock_200])

        with patch("app.services.pricing_service.httpx.AsyncClient", return_value=mock_client), \
             patch("app.services.pricing_service.time.sleep"):
            result = await pricing_service.refresh_currency_rates(realm="poe2")

        assert result == {"chaos": {"chaos_equivalent": 1.0}}

    @pytest.mark.asyncio
    async def test_refresh_network_error_then_success(self, pricing_service, mock_redis):
        """Network error triggers retry, then succeeds."""
        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.headers = {"X-Rate-Limit-Remaining": "59"}
        mock_200.json.return_value = {"chaos": {"chaos_equivalent": 1.0}}
        mock_200.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[httpx.RequestError("network down"), mock_200])

        with patch("app.services.pricing_service.httpx.AsyncClient", return_value=mock_client), \
             patch("app.services.pricing_service.time.sleep"):
            result = await pricing_service.refresh_currency_rates(realm="poe2")

        assert result == {"chaos": {"chaos_equivalent": 1.0}}

    @pytest.mark.asyncio
    async def test_refresh_http_error_raises(self, pricing_service, mock_redis):
        """Non-429 HTTP errors are raised immediately."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = _FakeHTTPStatusError(500, {})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.services.pricing_service.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await pricing_service.refresh_currency_rates(realm="poe2")

    @pytest.mark.asyncio
    async def test_refresh_exhausts_retries(self, pricing_service, mock_redis):
        """After max retries, RuntimeError is raised."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.RequestError("persistent failure"))

        with patch("app.services.pricing_service.httpx.AsyncClient", return_value=mock_client), \
             patch("app.services.pricing_service.time.sleep"):
            with pytest.raises(RuntimeError, match="Failed to fetch currency rates"):
                await pricing_service.refresh_currency_rates(realm="poe2")


class TestGetChaosEquivalent:
    """Tests for get_chaos_equivalent."""

    def test_returns_chaos_for_chaos(self, pricing_service, mock_redis):
        """Chaos orb should return amount * 1.0."""
        mock_redis.get.return_value = json.dumps({"chaos": {"chaos_equivalent": 1.0}})
        assert pricing_service.get_chaos_equivalent("chaos", 10.0) == 10.0

    def test_returns_divine_equivalent(self, pricing_service, mock_redis):
        """Divine orb should return amount * rate."""
        mock_redis.get.return_value = json.dumps({"divine": {"chaos_equivalent": 150.0}})
        assert pricing_service.get_chaos_equivalent("divine", 2.0) == 300.0

    def test_unknown_currency_returns_zero(self, pricing_service, mock_redis):
        """Unknown currency returns 0.0."""
        mock_redis.get.return_value = json.dumps({"chaos": {"chaos_equivalent": 1.0}})
        assert pricing_service.get_chaos_equivalent("unknown", 1.0) == 0.0

    def test_no_cache_returns_zero(self, pricing_service, mock_redis):
        """No cached rates returns 0.0."""
        mock_redis.get.return_value = None
        assert pricing_service.get_chaos_equivalent("chaos", 1.0) == 0.0

    def test_rounds_to_4_decimals(self, pricing_service, mock_redis):
        """Result is rounded to 4 decimal places."""
        mock_redis.get.return_value = json.dumps({"divine": {"chaos_equivalent": 150.12345}})
        result = pricing_service.get_chaos_equivalent("divine", 1.0)
        assert result == 150.1234


class TestGetCachedRates:
    """Tests for get_cached_rates."""

    def test_returns_parsed_data(self, pricing_service, mock_redis):
        """Returns parsed dict when cache hit."""
        data = {"chaos": {"chaos_equivalent": 1.0}}
        mock_redis.get.return_value = json.dumps(data)
        assert pricing_service.get_cached_rates() == data

    def test_returns_none_on_miss(self, pricing_service, mock_redis):
        """Returns None when cache miss."""
        mock_redis.get.return_value = None
        assert pricing_service.get_cached_rates() is None

    def test_returns_none_on_bad_json(self, pricing_service, mock_redis):
        """Returns None when cached value is not valid JSON."""
        mock_redis.get.return_value = "not json"
        assert pricing_service.get_cached_rates() is None
