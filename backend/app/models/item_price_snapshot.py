"""Database model for multi-category item price snapshots.

Extends price tracking beyond white equipment bases to cover:
currency (orbs, essences, runes, catalysts, ...), unique equipment,
skill gems, and any future category.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, JSON, Float, Index
from app.core.database import Base


class ItemPriceSnapshot(Base):
    """One row per (name_en, category, market, league) scan result."""
    __tablename__ = "item_price_snapshots"
    __table_args__ = (
        Index("ix_ips_market_league_cat_batch", "market", "league", "category", "scan_batch"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name_en = Column(String(256), nullable=False)
    name_cn = Column(String(256), nullable=True)
    category = Column(String(64), nullable=False)        # "currency_orb", "unique_jewel", "skill_gem", etc.
    chaos_price = Column(Float, nullable=True)           # cheapest listing in chaos eq
    divine_price = Column(Float, nullable=True)          # chaos_price / divine_rate
    median_chaos = Column(Float, nullable=True)          # median of fetched listings
    listing_count = Column(Integer, default=0)           # number of fetched listings with prices
    total_results = Column(Integer, default=0)           # Trade API total count
    confidence = Column(String(16), nullable=True)       # "high" (>=5 listings) / "low" (<5)
    prices_raw = Column(JSON, nullable=True)             # [{amount, currency, chaos_eq}]
    market = Column(String(16), nullable=False)          # "cn" / "global"
    league = Column(String(64), nullable=False)          # "奥术秘符" / "Runes of Aldur"
    scan_batch = Column(String(32), nullable=True)       # batch ID for grouping one scan run
    scanned_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
