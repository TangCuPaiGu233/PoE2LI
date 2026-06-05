"""API endpoint for PoB code decoding."""

from fastapi import APIRouter, HTTPException
from app.models.schemas import DecodeRequest, DecodeResponse, ErrorResponse
from app.services.pob_service import decode_pob

router = APIRouter()


@router.post("/api/builds/decode", response_model=DecodeResponse)
async def decode_build(req: DecodeRequest):
    """Decode a PoB share code into structured BuildData.

    Pure decode — no storage, no AI generation.
    Accepts a PoB code and returns structured JSON with build info, tree, skills, items, and stats.
    """
    result = decode_pob(req.pob_code)

    if isinstance(result, ErrorResponse):
        raise HTTPException(
            status_code=400,
            detail={"error": result.error, "reason": result.reason},
        )

    return result
