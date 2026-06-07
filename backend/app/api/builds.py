"""API endpoints for build CRUD operations."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.build import Build
from app.models.schemas import (
    CreateBuildRequest, BuildSummary, BuildDetail,
    ErrorResponse, AdminImportRequest, ChatRequest, ChatResponse
)
from app.services.pob_service import decode_pob
from app.tasks.worker import generate_homework_task

router = APIRouter()


@router.post("/api/builds", response_model=BuildSummary)
async def create_build(req: CreateBuildRequest, db: Session = Depends(get_db)):
    """Save a new build — decodes PoB code, stores in DB, and dispatches async AI task."""
    # Decode
    build_data = decode_pob(req.pob_code)
    if isinstance(build_data, ErrorResponse):
        raise HTTPException(
            status_code=400,
            detail={"error": build_data.error, "reason": build_data.reason},
        )

    # Save to DB with "pending" status
    build = Build(
        pob_code=req.pob_code,
        league=req.league,
        game_version=req.game_version or build_data.build.targetVersion,
        pob_version=build_data.build.targetVersion,
        class_name=build_data.build.className,
        ascendancy=build_data.build.ascendClassName,
        level=int(build_data.build.level) if build_data.build.level and build_data.build.level.isdigit() else None,
        source="user_submit",
        status="pending",
    )
    build.set_build_data(build_data.model_dump())
    db.add(build)
    db.commit()
    db.refresh(build)

    # Dispatch Celery task
    try:
        generate_homework_task.delay(build.id, build_data.model_dump())
    except Exception as e:
        # Graceful fallback if celery is not running in test env
        import logging
        logging.error(f"Failed to dispatch celery task, likely missing redis: {e}")

    return BuildSummary(
        id=build.id,
        status=build.status,
        league=build.league,
        game_version=build.game_version,
        build=build.get_build_data().get("build", {}),
    )


@router.post("/api/admin/import", response_model=list[BuildSummary])
async def admin_import_builds(req: AdminImportRequest, db: Session = Depends(get_db)):
    """Batch import builds from PoB codes or pobb.in URLs (Admin only)."""
    results = []
    
    for code in req.codes:
        # Decode
        build_data = decode_pob(code)
        if isinstance(build_data, ErrorResponse):
            continue # Skip failed imports in batch mode
            
        # Save to DB
        build = Build(
            pob_code=code,
            league=req.league,
            game_version=req.game_version or build_data.build.targetVersion,
            pob_version=build_data.build.targetVersion,
            class_name=build_data.build.className,
            ascendancy=build_data.build.ascendClassName,
            level=int(build_data.build.level) if build_data.build.level and build_data.build.level.isdigit() else None,
            source="operation_import",
            status="pending",
        )
        build.set_build_data(build_data.model_dump())
        db.add(build)
        db.commit()
        db.refresh(build)
        
        # Dispatch Celery task
        try:
            generate_homework_task.delay(build.id, build_data.model_dump())
        except Exception as e:
            import logging
            logging.error(f"Failed to dispatch celery task: {e}")
            
        results.append(
            BuildSummary(
                id=build.id,
                status=build.status,
                league=build.league,
                game_version=build.game_version,
                build=build.get_build_data().get("build", {}),
            )
        )
        
    return results


@router.post("/api/builds/{build_id}/chat", response_model=ChatResponse)
async def chat_with_build(build_id: int, req: ChatRequest, db: Session = Depends(get_db)):
    """Ask a question about a specific build."""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")
        
    # Import here to avoid circular imports if ai_service imports schemas
    from app.services.ai_service import chat_about_build
    
    answer = chat_about_build(build, req.question)
    return ChatResponse(answer=answer, context_used=["Build Data", "Homework"])


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
