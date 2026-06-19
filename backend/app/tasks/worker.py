"""Celery worker tasks for background processing."""

from app.tasks.celery_app import celery_app
from app.services.ai_service import generate_homework
from app.services.knowledge_service import ingest_build
from app.models.schemas import DecodeResponse
from app.core.database import SessionLocal
from app.models.build import Build
import logging

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=3)
def generate_homework_task(self, build_id: int, build_data_dict: dict):
    """Generate Chinese playbook via AI, update the DB record, and ingest into knowledge base."""
    logger.info(f"Starting homework generation for build_id={build_id}")
    
    db = SessionLocal()
    try:
        # Check if build exists
        build = db.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error(f"Build {build_id} not found in DB.")
            return False

        # If already done, skip
        if build.status == "done" and build.homework:
            logger.info(f"Build {build_id} already has homework. Skipping.")
            return True
            
        # Reconstruct DecodeResponse from dict
        build_data = DecodeResponse.model_validate(build_data_dict)
        
        # Call AI service
        try:
            homework = generate_homework(build_data)
        except Exception as exc:
            logger.error(f"AI generation failed for build {build_id}: {exc}")
            build.status = "failed"
            db.commit()
            raise self.retry(exc=exc, countdown=60)  # Retry after 60s
            
        # Update DB
        build.set_homework(homework)
        db.commit()
        logger.info(f"Homework generated and saved for build_id={build_id}")

        # ── RAG: Ingest into knowledge base ──
        try:
            n_chunks = ingest_build(db, build, homework)
            if n_chunks > 0:
                logger.info(f"Knowledge ingestion: {n_chunks} chunks created for build {build_id}")
        except Exception as e:
            # Ingestion failure is non-fatal — homework is already saved
            logger.warning(f"Knowledge ingestion failed for build {build_id}: {e}")
        
        return True
        
    except Exception as exc:
        logger.error(f"Error in generate_homework_task: {exc}")
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=1)
def scan_base_prices_task(self, market: str = "cn", league: str | None = None):
    """Daily scan of all equipment base prices on the Trade market.

    Scans normal-rarity listings for each base type, writes results to DB,
    then regenerates the loot filter with high-value bases.
    """
    logger.info(f"Starting base price scan: market={market}, league={league}")

    try:
        from app.services.base_scanner import scan_all_bases
        from app.services.filter_generator import generate_from_latest_scan

        # Load config
        from app.api.filter import _load_config
        cfg = _load_config()
        market = market or cfg.get("market", "cn")
        min_price = cfg.get("min_price_chaos", 50.0)
        min_results = cfg.get("min_results", 3)

        report = scan_all_bases(
            market=market,
            league=league,
            min_price_chaos=min_price,
            min_results=min_results,
        )

        # Auto-generate filter after scan
        try:
            gen_result = generate_from_latest_scan(
                market=market,
                league=league,
                item_level_min=cfg.get("item_level_min", 82),
            )
            logger.info(f"Filter generated: {gen_result.get('output_path')}")
        except Exception as e:
            logger.warning(f"Filter generation failed (non-fatal): {e}")

        logger.info(
            f"Base price scan complete: {report.high_value_count} high-value / "
            f"{report.scanned} scanned / {report.errors} errors"
        )
        return report.to_dict()

    except Exception as exc:
        logger.error(f"Base price scan failed: {exc}")
        raise self.retry(exc=exc, countdown=300)
