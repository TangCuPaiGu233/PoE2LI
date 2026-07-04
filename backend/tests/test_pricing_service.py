"""Unit tests for PricingService."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.pricing_service import PricingService


client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(redis_client: MagicMock | None = None) -> PricingService:
    svc = PricingService.__new__(PricingService)
    svc._redis = redis_client or MagicMock()
    return svc


_SAMPLE_RATES = {
    "chaos": {"chaos_equivalent": 1.0},
    "divine": {"chaos_equivalent": 120.5},
    "exalted": {"chaos_equivalent": 15.2},
}


def _make_http_status_error(
    status_code: int,
    headers: dict | None = None,
) -> httpx.HTTPStatusError:
    """Create a real-looking HTTPStatusError for testing."""
    request = MagicMock()
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    return httpx.HTTPStatusError(
        message=f"{status_code} error",
        request=request,
        response=response,
    )


# ---------------------------------------------------------------------------
# Tests: refresh_currency_rates
# ---------------------------------------------------------------------------

class TestRefreshCurrencyRates:
    """Tests for PricingService.refresh_currency_rates."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Happy path: API returns 200 with rates data."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _SAMPLE_RATES

        mock_redis = MagicMock()

        svc = _make_service(redis_client=mock_redis)

        with patch("app.services.pricing_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = False
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = await svc.refresh_currency_rates(realm="poe2")

        assert result == _SAMPLE_RATES
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == "pricing:rates:poe2"
        assert call_args[0][1] == 3600

    @pytest.mark.asyncio
    async def test_429_then_success(self):
        """First request 429s, second succeeds."""
        mock_429_response = MagicMock()
        mock_429_response.status_code = 429
        mock_429_response.headers = {}

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.raise_for_status = MagicMock()
        mock_200.json.return_value = _SAMPLE_RATES

        mock_redis = MagicMock()

        svc = _make_service(redis_client=mock_redis)

        with patch("app.services.pricing_service.httpx.AsyncClient") as mock_client_cls, \
             patch("app.services.pricing_service.time.sleep"):
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = False

            def get_side_effect(*args, **kwargs):
                mock_resp = MagicMock()
                mock_resp.raise_for_status.side_effect = (
                    _make_http_status_error(429)
                )
                return mock_resp

            mock_client.get.side_effect = [
                _make_http_status_error(429),
                mock_200,
            ]
            mock_client_cls.return_value = mock_client

            result = await svc.refresh_currency_rates(realm="poe2")

        assert result == _SAMPLE_RATES
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_429_with_retry_after_header(self):
        """429 with Retry-After header uses that delay."""
        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.raise_for_status = MagicMock()
        mock_200.json.return_value = _SAMPLE_RATES

        mock_redis = MagicMock()

        svc = _make_service(redis_client=mock_redis)

        with patch("app.services.pricing_service.httpx.AsyncClient") as mock_client_cls, \
             patch("app.services.pricing_service.time.sleep") as mock_sleep:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = False
            mock_client.get.side_effect = [
                _make_http_status_error(429, headers={"Retry-After": "2"}),
                mock_200,
            ]
            mock_client_cls.return_value = mock_client

            await svc.refresh_currency_rates(realm="poe2")

        mock_sleep.assert_called_once()
        assert mock_sleep.call_args[0][0] == 2.0

    @pytest.mark.asyncio
    async def test_http_error_raises(self):
        """Non-429 HTTP errors are raised immediately."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = _make_http_status_error(500)

        svc = _make_service()

        with patch("app.services.pricing_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = False
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            with pytest.raises(httpx.HTTPStatusError):
                await svc.refresh_currency_rates(realm="poe2")

    @pytest.mark.asyncio
    async def test_timeout_retries_then_raises(self):
        """Timeout errors retry, then raise RuntimeError after max retries."""
        svc = _make_service()

        with patch("app.services.pricing_service.httpx.AsyncClient") as mock_client_cls, \
             patch("app.services.pricing_service.time.sleep"):
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = False
            mock_client.get.side_effect = [
                httpx.TimeoutException("timeout"),
                httpx.TimeoutException("timeout"),
                httpx.TimeoutException("timeout"),
                httpx.TimeoutException("timeout"),
                httpx.TimeoutException("timeout"),
            ]
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="Failed to fetch currency rates"):
                await svc.refresh_currency_rates(realm="poe2")


# ---------------------------------------------------------------------------
# Tests: get_chaos_equivalent
# ---------------------------------------------------------------------------

class TestGetChaosEquivalent:
    """Tests for PricingService.get_chaos_equivalent."""

    def test_known_currency(self):
        """Returns correct chaos equivalent for known currency."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(_SAMPLE_RATES)

        svc = _make_service(redis_client=mock_redis)
        result = svc.get_chaos_equivalent("divine", amount=2.0)

        assert result == pytest.approx(241.0)

    def test_chaos_currency_returns_amount(self):
        """Chaos orb returns the amount unchanged."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(_SAMPLE_RATES)

        svc = _make_service(redis_client=mock_redis)
        result = svc.get_chaos_equivalent("chaos", amount=5.0)

        assert result == pytest.approx(5.0)

    def test_no_cache_returns_zero(self):
        """Returns 0.0 when no cached rates exist."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        svc = _make_service(redis_client=mock_redis)
        result = svc.get_chaos_equivalent("divine")

        assert result == 0.0

    def test_unknown_currency_returns_zero(self):
        """Returns 0.0 for unknown currency."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(_SAMPLE_RATES)

        svc = _make_service(redis_client=mock_redis)
        result = svc.get_chaos_equivalent("unknown_currency")

        assert result == 0.0

    def test_invalid_cache_returns_zero(self):
        """Returns 0.0 when cached data is malformed."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = "not valid json {{{"

        svc = _make_service(redis_client=mock_redis)
        result = svc.get_chaos_equivalent("divine")

        assert result == 0.0

    def test_nested_rates_shape(self):
        """Handles nested 'rates' key in cached data."""
        nested_data = {"rates": _SAMPLE_RATES}
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(nested_data)

        svc = _make_service(redis_client=mock_redis)
        result = svc.get_chaos_equivalent("exalted", amount=1.0)

        assert result == pytest.approx(15.2)


# ---------------------------------------------------------------------------
# Tests: get_cached_rates
# ---------------------------------------------------------------------------

class TestGetCachedRates:
    """Tests for PricingService.get_cached_rates."""

    def test_returns_cached_data(self):
        """Returns parsed dict when cache exists."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(_SAMPLE_RATES)

        svc = _make_service(redis_client=mock_redis)
        result = svc.get_cached_rates(realm="poe2")

        assert result == _SAMPLE_RATES
        mock_redis.get.assert_called_once_with("pricing:rates:poe2")

    def test_returns_none_when_no_cache(self):
        """Returns None when no cached data."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        svc = _make_service(redis_client=mock_redis)
        result = svc.get_cached_rates(realm="poe2")

        assert result is None

    def test_returns_none_on_parse_error(self):
        """Returns None when cached data is malformed."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = "not valid json"

        svc = _make_service(redis_client=mock_redis)
        result = svc.get_cached_rates(realm="poe2")

        assert result is None


# ---------------------------------------------------------------------------
# Tests: API endpoints
# ---------------------------------------------------------------------------

class TestPricingAPI:
    """Tests for /api/pricing/* endpoints."""

    def setup_method(self):
        """Reset lazy singleton before each test to avoid cross-test pollution."""
        from app.api.pricing import _LazyPricingService
        _LazyPricingService._instance = None

    def test_get_currency_rates_empty(self):
        """GET /api/pricing/currency returns 200 with empty rates when no cache."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        with patch("app.services.pricing_service.get_redis", return_value=mock_redis):
            response = client.get("/api/pricing/currency")

        assert response.status_code == 200
        data = response.json()
        assert "rates" in data
        assert "last_updated" in data
        assert data["rates"] == {}

    def test_convert_endpoint_exists(self):
        """POST /api/pricing/convert is registered (returns 422 for empty body)."""
        response = client.post("/api/pricing/convert", json={})
        assert response.status_code == 422

    def test_convert_endpoint_success(self):
        """POST /api/pricing/convert returns chaos equivalent."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(_SAMPLE_RATES)

        with patch("app.services.pricing_service.get_redis", return_value=mock_redis):
            response = client.post(
                "/api/pricing/convert",
                json={"currency": "divine", "amount": 2.0},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["currency"] == "divine"
        assert data["amount"] == 2.0
        assert data["chaos_equivalent"] == pytest.approx(241.0)
        assert "last_updated" in data

    def test_convert_endpoint_unknown_currency(self):
        """POST /api/pricing/convert returns 0.0 for unknown currency."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(_SAMPLE_RATES)

        with patch("app.services.pricing_service.get_redis", return_value=mock_redis):
            response = client.post(
                "/api/pricing/convert",
                json={"currency": "unknown", "amount": 1.0},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["chaos_equivalent"] == 0.0

    def test_convert_endpoint_no_cache(self):
        """POST /api/pricing/convert returns 0.0 when no cache."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        with patch("app.services.pricing_service.get_redis", return_value=mock_redis):
            response = client.post(
                "/api/pricing/convert",
                json={"currency": "divine", "amount": 1.0},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["chaos_equivalent"] == 0.0

    def test_convert_endpoint_default_amount(self):
        """POST /api/pricing/convert uses default amount=1.0."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(_SAMPLE_RATES)

        with patch("app.services.pricing_service.get_redis", return_value=mock_redis):
            response = client.post(
                "/api/pricing/convert",
                json={"currency": "exalted"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["amount"] == 1.0
        assert data["chaos_equivalent"] == pytest.approx(15.2)
