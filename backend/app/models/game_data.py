"""Model for raw game data extracted from GGPK."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Index
from app.core.database import Base


class GameDatum(Base):
    """Stores structured game data extracted from PoE2 Content.ggpk.

    Each row is one record from a game data table (e.g., ActiveSkills, BaseItemTypes).
    Contains English, Traditional Chinese and Simplified Chinese text.

    Usage:
        # Lookup a skill by ID
        session.query(GameDatum).filter_by(table_name="ActiveSkills", row_key="ground_slam").first()

        # Search for items by simplified Chinese name
        session.query(GameDatum).filter(
            GameDatum.table_name == "BaseItemTypes",
            GameDatum.name_sc.ilike("%混沌%")
        ).all()
    """
    __tablename__ = "game_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    table_name = Column(String(64), nullable=False, index=True)   # e.g. ActiveSkills, BaseItemTypes
    row_key = Column(String(256), nullable=False)                  # e.g. ground_slam, row index
    name_en = Column(String(256), nullable=True, index=True)       # English display name
    name_tc = Column(String(256), nullable=True, index=True)       # Traditional Chinese name
    name_sc = Column(String(256), nullable=True, index=True)       # Simplified Chinese name
    data = Column(JSON, nullable=False)                            # Merged row data {en:{}, tc:{}, sc:{}}
    source = Column(String(16), nullable=False, default="ggpk")   # Data source
    game_version = Column(String(32), nullable=True)               # Game version
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_game_data_table_key", "table_name", "row_key", unique=True),
    )

    def get_name(self, locale="en"):
        """Get display name for given locale."""
        if locale == "sc":
            return self.name_sc or self.name_tc or self.name_en
        if locale == "tc":
            return self.name_tc or self.name_en
        return self.name_en

    def to_dict(self):
        return {
            "id": self.id,
            "table_name": self.table_name,
            "row_key": self.row_key,
            "name_en": self.name_en,
            "name_tc": self.name_tc,
            "name_sc": self.name_sc,
            "data": self.data,
        }
