"""Database model for base item price snapshots."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Float, Boolean
from app.core.database import Base


class BasePriceSnapshot(Base):
    """One row per (base_type, market, league) scan result."""
    __tablename__ = "base_price_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    base_name_en = Column(String(128), nullable=False, index=True)
    base_name_cn = Column(String(128), nullable=True)
    item_category = Column(String(64), nullable=True)   # e.g. "armour.helmet"
    group_id = Column(String(32), nullable=True)        # e.g. "armour"
    market = Column(String(16), nullable=False)         # "cn" / "global"
    league = Column(String(64), nullable=False)         # "奥术秘符" / "Standard"
    total_results = Column(Integer, default=0)          # Trade API total count
    cheapest_price_chaos = Column(Float, nullable=True) # cheapest listing in chaos eq
    median_price_chaos = Column(Float, nullable=True)   # median of fetched listings
    prices_raw = Column(JSON, nullable=True)            # [{amount, currency, chaos_eq}]
    is_high_value = Column(Boolean, default=False)
    scan_batch = Column(String(32), nullable=True)      # batch ID for grouping one scan run
    scanned_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
