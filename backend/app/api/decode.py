"""API endpoint for PoB code decoding."""

from fastapi import APIRouter
from app.models.schemas import DecodeRequest, DecodeResponse, ErrorResponse
from app.services.pob_service import decode_pob

router = APIRouter()


@router.post(
    "/api/builds/decode",
    response_model=DecodeResponse | ErrorResponse,
    responses={400: {"model": ErrorResponse}},
)
async def decode_build(req: DecodeRequest):
    """Decode a PoB share code into structured BuildData.

    Accepts a PoB code (base64+zlib encoded XML), decodes and parses it,
    and returns structured JSON with build info, tree, skills, items, and stats.
    """
    result = decode_pob(req.pob_code)

    if isinstance(result, ErrorResponse):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content=result.model_dump())

    return result
