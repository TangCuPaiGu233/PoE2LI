"""Database model for builds."""

import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.core.database import Base


class Build(Base):
    __tablename__ = "builds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pob_code = Column(Text, nullable=False)
    build_data = Column(Text, nullable=False)  # JSON string of parsed BuildData
    homework = Column(Text, nullable=True)  # JSON string of AI-generated playbook
    league = Column(String(50), nullable=True)
    game_version = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False, default="parsed")  # pending/parsed/done/failed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_build_data(self) -> dict:
        return json.loads(self.build_data)

    def set_build_data(self, data: dict):
        self.build_data = json.dumps(data, ensure_ascii=False)

    def get_homework(self) -> dict | None:
        if self.homework:
            return json.loads(self.homework)
        return None

    def set_homework(self, data: dict):
        self.homework = json.dumps(data, ensure_ascii=False)
        self.status = "done"
