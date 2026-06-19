"""API endpoints for loot filter generation and base price scanning."""

import logging
import os
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.models.base_price import BasePriceSnapshot  # noqa: ensure model registered for create_all
from app.models.item_price_snapshot import ItemPriceSnapshot  # noqa: ensure model registered for create_all

logger = logging.getLogger(__name__)

router = APIRouter()

# ── In-memory scan state (lightweight; Celery task does the real work) ──
_scan_state: dict = {"running": False, "task_id": None, "report": None, "error": None}
_price_scan_state: dict = {"running": False, "report": None, "error": None}


# ── Request / Response models ──

class ScanRequest(BaseModel):
    market: Literal["cn", "global"] = Field("cn", description="交易市场")
    league: str | None = Field(None, description="赛季名称")
    min_price_chaos: float = Field(50.0, description="最低价阈值(混沌石)")
    min_results: int = Field(3, description="最少在售数量")
    max_bases: int | None = Field(None, description="限制扫描底材数(测试用)")


class PriceScanRequest(BaseModel):
    market: Literal["cn", "global"] = Field("cn", description="交易市场")
    league: str | None = Field(None, description="赛季名称")
    categories: list[str] | None = Field(
        None, description="要扫描的品类列表，空=全部。可选: currency, unique, gem, white_base"
    )
    max_per_category: int | None = Field(None, description="每品类最多扫描数(测试用)")


class GenerateWithPricesRequest(BaseModel):
    market: Literal["cn", "global"] = Field("cn")
    league: str | None = None
    hide_threshold_chaos: float = Field(1.0, description="隐藏阈值(混沌石): 低于此价格的物品被隐藏 (1c=Chaos Orb)")
    item_level_min: int = Field(82, description="最低物品等级")


class FilterConfigUpdate(BaseModel):
    min_price_chaos: float | None = None
    min_results: int | None = None
    item_level_min: int | None = None
    template: str | None = None
    market: Literal["cn", "global"] | None = None
    deprecated_uniques: list[str] | None = None


class GenerateRequest(BaseModel):
    market: Literal["cn", "global"] = Field("cn")
    league: str | None = None
    item_level_min: int = Field(82, description="最低物品等级")


# ── Config file ──
_CONFIG_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "filter_config.json")
)


def _load_config() -> dict:
    import json
    if os.path.isfile(_CONFIG_PATH):
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {
        "min_price_chaos": 50.0,
        "min_results": 3,
        "item_level_min": 82,
        "market": "cn",
        "deprecated_uniques": [],
    }


def _save_config(cfg: dict):
    import json
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ── Endpoints ──

@router.post("/api/filter/scan")
async def trigger_scan(req: ScanRequest, background_tasks: BackgroundTasks):
    """Trigger a base price scan (runs in background thread)."""
    if _scan_state.get("running"):
        return {"status": "already_running", "task_id": _scan_state.get("task_id")}

    def _run_scan():
        _scan_state["running"] = True
        _scan_state["error"] = None
        try:
            from app.services.base_scanner import scan_all_bases
            report = scan_all_bases(
                market=req.market,
                league=req.league,
                min_price_chaos=req.min_price_chaos,
                min_results=req.min_results,
                max_bases=req.max_bases,
            )
            _scan_state["report"] = report.to_dict()
            logger.info(f"Scan complete: {report.high_value_count} high-value bases found")
        except Exception as e:
            logger.exception("Scan failed")
            _scan_state["error"] = str(e)
        finally:
            _scan_state["running"] = False

    background_tasks.add_task(_run_scan)
    _scan_state["running"] = True
    return {"status": "started", "market": req.market, "league": req.league}


@router.get("/api/filter/scan/status")
async def scan_status():
    """Check scan progress."""
    return {
        "running": _scan_state.get("running", False),
        "report": _scan_state.get("report"),
        "error": _scan_state.get("error"),
    }


@router.get("/api/filter/bases")
async def list_bases(
    market: Literal["cn", "global"] = "cn",
    league: str | None = None,
    high_value_only: bool = True,
):
    """List scanned base prices from the latest scan batch."""
    from app.services.base_scanner import get_latest_high_value_bases
    from app.core.database import SessionLocal
    from app.models.base_price import BasePriceSnapshot
    from app.services.trade_realm import resolve_league

    resolved_league = resolve_league(market, league)
    db = SessionLocal()
    try:
        # Find latest batch
        latest = (
            db.query(BasePriceSnapshot)
            .filter(
                BasePriceSnapshot.market == market,
                BasePriceSnapshot.league == resolved_league,
            )
            .order_by(BasePriceSnapshot.scanned_at.desc())
            .first()
        )
        if not latest:
            return {"bases": [], "batch_id": None, "message": "暂无扫描数据"}

        batch_id = latest.scan_batch
        query = db.query(BasePriceSnapshot).filter(
            BasePriceSnapshot.scan_batch == batch_id,
        )
        if high_value_only:
            query = query.filter(BasePriceSnapshot.is_high_value == True)

        rows = query.order_by(BasePriceSnapshot.cheapest_price_chaos.desc()).all()
        return {
            "batch_id": batch_id,
            "scanned_at": latest.scanned_at.isoformat(),
            "total": len(rows),
            "bases": [
                {
                    "name_en": r.base_name_en,
                    "name_cn": r.base_name_cn,
                    "category": r.item_category,
                    "group_id": r.group_id,
                    "total_results": r.total_results,
                    "cheapest_chaos": r.cheapest_price_chaos,
                    "median_chaos": r.median_price_chaos,
                    "is_high_value": r.is_high_value,
                }
                for r in rows
            ],
        }
    finally:
        db.close()


@router.post("/api/filter/generate")
async def generate_filter(req: GenerateRequest):
    """Generate a .filter file from latest scan data."""
    from app.services.filter_generator import generate_from_latest_scan

    result = generate_from_latest_scan(
        market=req.market,
        league=req.league,
        item_level_min=req.item_level_min,
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/api/filter/download")
async def download_filter():
    """Download the latest generated .filter file."""
    from app.services.filter_generator import _USER_FILTER_DIR

    # Find the most recent generated filter
    if not os.path.isdir(_USER_FILTER_DIR):
        raise HTTPException(status_code=404, detail="没有可用的过滤器文件")

    filters = [
        f for f in os.listdir(_USER_FILTER_DIR)
        if f.endswith(".filter") and "AI高价值底材" in f
    ]
    if not filters:
        raise HTTPException(status_code=404, detail="没有已生成的过滤器，请先调用 /api/filter/generate")

    latest = sorted(filters)[-1]
    path = os.path.join(_USER_FILTER_DIR, latest)
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=latest,
    )


@router.get("/api/filter/config")
async def get_config():
    """Get current filter configuration."""
    return _load_config()


@router.post("/api/filter/config")
async def update_config(update: FilterConfigUpdate):
    """Update filter configuration."""
    cfg = _load_config()
    for key, val in update.model_dump(exclude_none=True).items():
        cfg[key] = val
    _save_config(cfg)
    return {"status": "updated", "config": cfg}


@router.get("/api/filter/templates")
async def list_templates():
    """List available filter templates."""
    from app.services.filter_generator import _FILTER_TEMPLATE_DIR

    templates = []
    # Check template dir
    if os.path.isdir(_FILTER_TEMPLATE_DIR):
        for f in sorted(os.listdir(_FILTER_TEMPLATE_DIR)):
            if f.endswith(".filter"):
                templates.append({"name": f, "path": os.path.join(_FILTER_TEMPLATE_DIR, f)})

    # Also check user's PoE2 directory
    user_dir = os.path.expanduser(
        os.path.join("~", "Documents", "My Games", "Path of Exile 2")
    )
    if os.path.isdir(user_dir):
        for f in sorted(os.listdir(user_dir)):
            if f.endswith(".filter") and "asmco" in f.lower():
                templates.append({"name": f, "path": os.path.join(user_dir, f), "source": "user"})

    return {"templates": templates}


# ═══════════════════════════════════════════════════════════
#  Multi-category price scan endpoints
# ═══════════════════════════════════════════════════════════


@router.post("/api/filter/price-scan")
async def trigger_price_scan(req: PriceScanRequest, background_tasks: BackgroundTasks):
    """Trigger a multi-category price scan (runs in background thread)."""
    if _price_scan_state.get("running"):
        return {"status": "already_running"}

    def _run_price_scan():
        _price_scan_state["running"] = True
        _price_scan_state["error"] = None
        try:
            from app.services.price_scanner import scan_all_categories
            report, _snapshots = scan_all_categories(
                market=req.market,
                league=req.league,
                categories=req.categories,
                max_items_per_category=req.max_per_category,
            )
            _price_scan_state["report"] = report.to_dict()
            logger.info(f"Price scan complete: {report.priced} items priced")
        except Exception as e:
            logger.exception("Price scan failed")
            _price_scan_state["error"] = str(e)
        finally:
            _price_scan_state["running"] = False

    background_tasks.add_task(_run_price_scan)
    _price_scan_state["running"] = True
    return {"status": "started", "market": req.market, "league": req.league}


@router.get("/api/filter/price-scan/status")
async def price_scan_status():
    """Check multi-category price scan progress."""
    return {
        "running": _price_scan_state.get("running", False),
        "report": _price_scan_state.get("report"),
        "error": _price_scan_state.get("error"),
    }


@router.get("/api/filter/prices")
async def list_prices(
    market: Literal["cn", "global"] = "cn",
    league: str | None = None,
    category: str | None = None,
    min_price: float = 0,
):
    """List scanned item prices from the latest multi-category scan batch."""
    from app.core.database import SessionLocal
    from app.models.item_price_snapshot import ItemPriceSnapshot
    from app.services.trade_realm import resolve_league

    resolved_league = resolve_league(market, league)
    db = SessionLocal()
    try:
        latest = (
            db.query(ItemPriceSnapshot)
            .filter(
                ItemPriceSnapshot.market == market,
                ItemPriceSnapshot.league == resolved_league,
            )
            .order_by(ItemPriceSnapshot.scanned_at.desc())
            .first()
        )
        if not latest:
            return {"items": [], "batch_id": None, "message": "暂无价格扫描数据"}

        batch_id = latest.scan_batch
        query = db.query(ItemPriceSnapshot).filter(
            ItemPriceSnapshot.scan_batch == batch_id,
        )
        if category:
            query = query.filter(ItemPriceSnapshot.category == category)
        if min_price > 0:
            query = query.filter(ItemPriceSnapshot.chaos_price >= min_price)

        rows = query.order_by(ItemPriceSnapshot.chaos_price.desc()).all()

        # Category summary
        cat_counts: dict[str, int] = {}
        for r in rows:
            cat_counts[r.category] = cat_counts.get(r.category, 0) + 1

        return {
            "batch_id": batch_id,
            "scanned_at": latest.scanned_at.isoformat(),
            "total": len(rows),
            "category_counts": cat_counts,
            "items": [
                {
                    "name_en": r.name_en,
                    "name_cn": r.name_cn,
                    "category": r.category,
                    "chaos_price": r.chaos_price,
                    "divine_price": r.divine_price,
                    "median_chaos": r.median_chaos,
                    "listing_count": r.listing_count,
                    "confidence": r.confidence,
                }
                for r in rows
            ],
        }
    finally:
        db.close()


@router.post("/api/filter/generate-with-prices")
async def generate_filter_with_prices(req: GenerateWithPricesRequest):
    """Generate a .filter file with multi-category price tiers."""
    from app.services.filter_generator import generate_from_latest_prices

    result = generate_from_latest_prices(
        market=req.market,
        league=req.league,
        hide_threshold_chaos=req.hide_threshold_chaos,
        item_level_min=req.item_level_min,
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/api/filter/download-price")
async def download_price_filter():
    """Download the latest price-aware .filter file."""
    from app.services.filter_generator import _USER_FILTER_DIR

    if not os.path.isdir(_USER_FILTER_DIR):
        raise HTTPException(status_code=404, detail="没有可用的过滤器文件")

    filters = [
        f for f in os.listdir(_USER_FILTER_DIR)
        if f.endswith(".filter") and "AI价格过滤器" in f
    ]
    if not filters:
        raise HTTPException(status_code=404, detail="没有已生成的价格过滤器，请先调用 /api/filter/generate-with-prices")

    latest = sorted(filters)[-1]
    path = os.path.join(_USER_FILTER_DIR, latest)
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=latest,
    )
