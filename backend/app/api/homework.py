"""API endpoint for generating build playbooks (homework)."""

from fastapi import APIRouter, HTTPException
from app.models.schemas import DecodeRequest, ErrorResponse
from app.services.pob_service import decode_pob
from app.services.ai_service import generate_homework

router = APIRouter()


@router.post("/api/builds/homework")
async def generate_build_homework(req: DecodeRequest):
    """Generate a Chinese playbook from a PoB share code.

    Decodes the PoB code, extracts build data, and uses AI to generate
    a structured Chinese playbook with:
    - core_idea: Build philosophy
    - core_items: Essential equipment
    - budget_alternatives: Cheaper options
    - talent_highlights: Passive tree highlights
    - strength_review: Build assessment
    """
    # Step 1: Decode
    build_data = decode_pob(req.pob_code)
    if isinstance(build_data, ErrorResponse):
        raise HTTPException(
            status_code=400,
            detail={"error": build_data.error, "reason": build_data.reason},
        )

    # Step 2: Generate homework
    homework = generate_homework(build_data)

    return homework
