"""Database configuration — SQLite for dev/test, PostgreSQL for production."""

import os
import sqlalchemy as sa
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.schema import DDL

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    # Use PostgreSQL if DATABASE_URL is provided (e.g. from docker-compose)
    engine = create_engine(DATABASE_URL)
    # Ensure pgvector extension exists on Postgres
    event.listen(engine, "before_cursor_execute", DDL("CREATE EXTENSION IF NOT EXISTS vector"))
else:
    # SQLite fallback — use /app/data in Docker, local file in dev
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "poe2li.db")
    # Use absolute path for sqlite in windows
    if os.name == 'nt':
        DATABASE_URL = f"sqlite:///{DB_PATH.replace(chr(92), '/')}"
    else:
        DATABASE_URL = f"sqlite:///{DB_PATH}"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    
    # SQLite does not support pgvector. We will monkey-patch the Vector type 
    # to be treated as a standard JSON column during local dev table creation
    from sqlalchemy.types import TypeDecorator
    class SQLiteVector(TypeDecorator):
        impl = sa.JSON
        cache_ok = True
        
        def process_bind_param(self, value, dialect):
            if value is not None:
                if isinstance(value, str):
                    return value
                import json
                return json.dumps(list(value))
            return None
            
        def process_result_value(self, value, dialect):
            if value is not None:
                if isinstance(value, str):
                    import json
                    return json.loads(value)
                return value
            return None
            
    # Swap out Vector locally before models are loaded
    import pgvector.sqlalchemy
    pgvector.sqlalchemy.Vector = SQLiteVector
    
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
