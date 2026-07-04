"""API endpoints for currency pricing."""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.pricing_service import PricingService

logger = logging.getLogger(__name__)

router = APIRouter()


class _LazyPricingService:
    """Lazy singleton wrapper to avoid Redis connection at import time."""

    _instance: PricingService | None = None

    @classmethod
    def get(cls) -> PricingService:
        if cls._instance is None:
            cls._instance = PricingService()
        return cls._instance


_pricing_service = _LazyPricingService()


class PricingResponse(BaseModel):
    """Response schema for /api/pricing/currency."""

    rates: dict[str, Any]
    last_updated: str


class ConvertRequest(BaseModel):
    """Request schema for /api/pricing/convert."""

    currency: str
    amount: float = 1.0


class ConvertResponse(BaseModel):
    """Response schema for /api/pricing/convert."""

    currency: str
    amount: float
    chaos_equivalent: float
    last_updated: str


@router.get("/api/pricing/currency", response_model=PricingResponse)
async def get_currency_rates() -> PricingResponse:
    """Return cached currency exchange rates.

    Response format:
        {
            "rates": {...},
            "last_updated": "ISO8601"
        }
    """
    data = _pricing_service.get().get_cached_rates(realm="poe2")
    if data is None:
        # Return empty payload; background task will refresh shortly
        return PricingResponse(rates={}, last_updated=datetime.now(timezone.utc).isoformat())

    last_updated = datetime.now(timezone.utc).isoformat()
    return PricingResponse(rates=data, last_updated=last_updated)


@router.post("/api/pricing/convert", response_model=ConvertResponse)
async def convert_currency(payload: ConvertRequest) -> ConvertResponse:
    """Convert a currency amount to its chaos orb equivalent.

    Request body:
        {
            "currency": "divine",
            "amount": 2.5
        }

    Response format:
        {
            "currency": "divine",
            "amount": 2.5,
            "chaos_equivalent": 150.0,
            "last_updated": "ISO8601"
        }
    """
    chaos_equiv = _pricing_service.get().get_chaos_equivalent(
        currency=payload.currency,
        amount=payload.amount,
    )
    return ConvertResponse(
        currency=payload.currency,
        amount=payload.amount,
        chaos_equivalent=chaos_equiv,
        last_updated=datetime.now(timezone.utc).isoformat(),
    )
