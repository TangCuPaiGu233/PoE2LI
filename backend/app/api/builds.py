"""API endpoints for build CRUD operations."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.build import Build
from app.models.schemas import DecodeRequest, ErrorResponse
from app.services.pob_service import decode_pob
from app.services.ai_service import generate_homework

router = APIRouter()


@router.post("/api/builds")
async def create_build(req: DecodeRequest, db: Session = Depends(get_db)):
    """Save a new build — decodes PoB code and stores BuildData."""
    # Decode
    build_data = decode_pob(req.pob_code)
    if isinstance(build_data, ErrorResponse):
        raise HTTPException(status_code=400, detail=build_data.error)

    # Generate homework
    homework = generate_homework(build_data)

    # Save to DB
    build = Build(
        pob_code=req.pob_code,
        league=req.league,
        game_version=req.game_version or build_data.build.targetVersion,
        status="done",
    )
    build.set_build_data(build_data.model_dump())
    build.set_homework(homework)

    db.add(build)
    db.commit()
    db.refresh(build)

    return {
        "id": build.id,
        "status": build.status,
        "league": build.league,
        "game_version": build.game_version,
        "build": build.get_build_data().get("build", {}),
    }


@router.get("/api/builds")
async def list_builds(db: Session = Depends(get_db)):
    """List all saved builds."""
    builds = db.query(Build).order_by(Build.created_at.desc()).limit(50).all()
    return [
        {
            "id": b.id,
            "status": b.status,
            "league": b.league,
            "build": b.get_build_data().get("build", {}),
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b in builds
    ]


@router.get("/api/builds/{build_id}")
async def get_build(build_id: int, db: Session = Depends(get_db)):
    """Get a specific build by ID."""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    return {
        "id": build.id,
        "status": build.status,
        "league": build.league,
        "game_version": build.game_version,
        "build": build.get_build_data(),
        "homework": build.get_homework(),
        "created_at": build.created_at.isoformat() if build.created_at else None,
    }
