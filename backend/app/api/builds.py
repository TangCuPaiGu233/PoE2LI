"""API endpoints for build CRUD operations."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.build import Build
from app.models.schemas import (
    CreateBuildRequest, BuildSummary, BuildDetail,
    ErrorResponse,
)
from app.services.pob_service import decode_pob
from app.services.ai_service import generate_homework

router = APIRouter()


@router.post("/api/builds", response_model=BuildSummary)
async def create_build(req: CreateBuildRequest, db: Session = Depends(get_db)):
    """Save a new build — decodes PoB code, generates homework, stores in DB."""
    # Decode
    build_data = decode_pob(req.pob_code)
    if isinstance(build_data, ErrorResponse):
        raise HTTPException(
            status_code=400,
            detail={"error": build_data.error, "reason": build_data.reason},
        )

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

    return BuildSummary(
        id=build.id,
        status=build.status,
        league=build.league,
        game_version=build.game_version,
        build=build.get_build_data().get("build", {}),
    )


@router.get("/api/builds", response_model=list[BuildSummary])
async def list_builds(db: Session = Depends(get_db)):
    """List all saved builds."""
    builds = db.query(Build).order_by(Build.created_at.desc()).limit(50).all()
    return [
        BuildSummary(
            id=b.id,
            status=b.status,
            league=b.league,
            game_version=b.game_version,
            build=b.get_build_data().get("build", {}),
        )
        for b in builds
    ]


@router.get("/api/builds/{build_id}", response_model=BuildDetail)
async def get_build(build_id: int, db: Session = Depends(get_db)):
    """Get a specific build by ID with full data and homework."""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    full_data = build.get_build_data()

    return BuildDetail(
        id=build.id,
        status=build.status,
        league=build.league,
        game_version=build.game_version,
        build=full_data.get("build", {}),
        treeSpecs=full_data.get("treeSpecs", []),
        skillSets=full_data.get("skillSets", []),
        items=full_data.get("items", []),
        playerStats=full_data.get("playerStats", {}),
        homework=build.get_homework(),
        created_at=build.created_at.isoformat() if build.created_at else None,
    )
