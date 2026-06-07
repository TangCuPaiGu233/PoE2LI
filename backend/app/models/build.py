"""Database model for builds."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Float, Boolean
from pgvector.sqlalchemy import Vector
from app.core.database import Base


class Build(Base):
    __tablename__ = "builds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pob_code = Column(Text, nullable=False)
    pob_version = Column(String(32), nullable=True)
    class_name = Column("class", String(64), nullable=True)  # 'class' is a reserved keyword in Python
    ascendancy = Column(String(64), nullable=True)
    main_skill = Column(String(128), nullable=True)
    level = Column(Integer, nullable=True)
    build_data = Column(JSON, nullable=False)  # Parsed BuildData
    homework = Column(JSON, nullable=True)  # AI-generated playbook
    league = Column(String(64), nullable=True)
    game_version = Column(String(32), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending/parsed/done/failed
    source = Column(String(32), nullable=True) # user_submit / operation_import
    quality_score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def get_build_data(self) -> dict:
        return self.build_data if self.build_data else {}

    def set_build_data(self, data: dict):
        self.build_data = data

    def get_homework(self) -> dict | None:
        return self.homework

    def set_homework(self, data: dict):
        self.homework = data
        self.status = "done"


class ModTranslation(Base):
    __tablename__ = "mod_translations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    mod_en = Column(Text, unique=True, nullable=False)
    mod_zh = Column(Text, nullable=False)
    source = Column(String(16), nullable=True) # poe2db / ai / manual
    verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1024), nullable=True) # mimo-v2.5 embeddings or bge-m3 etc
    league = Column(String(64), nullable=True)
    game_version = Column(String(32), nullable=True)
    source = Column(String(64), nullable=True) # pob / wiki / poe2db
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

