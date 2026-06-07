"""Celery worker tasks for background processing."""

from app.tasks.celery_app import celery_app
from app.services.ai_service import generate_homework
from app.models.schemas import DecodeResponse
from app.core.database import SessionLocal
from app.models.build import Build
import logging

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=3)
def generate_homework_task(self, build_id: int, build_data_dict: dict):
    """Generate Chinese playbook via AI and update the DB record."""
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
        return True
        
    except Exception as exc:
        logger.error(f"Error in generate_homework_task: {exc}")
        db.rollback()
        raise
    finally:
        db.close()
