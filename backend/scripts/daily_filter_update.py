"""Daily cron job: scan all item prices and regenerate the loot filter.

Usage:
    python scripts/daily_filter_update.py
    python scripts/daily_filter_update.py --market cn --categories currency,unique
    python scripts/daily_filter_update.py --market cn --max-per-category 20 --dry-run
    python scripts/daily_filter_update.py --market global --league Standard

Scheduled via cron or Windows Task Scheduler to run once daily (e.g. 06:00 AM).
"""

import argparse
import logging
import os
import sys
import time

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import engine, Base

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("daily_filter_update")


def main():
    parser = argparse.ArgumentParser(description="Daily price scan + filter generation")
    parser.add_argument("--market", default="cn", choices=["cn", "global"], help="交易市场")
    parser.add_argument("--league", default=None, help="赛季名称 (默认自动检测)")
    parser.add_argument(
        "--categories", default=None,
        help="逗号分隔的品类列表: currency,unique,gem,white_base (默认全部)",
    )
    parser.add_argument("--max-per-category", type=int, default=None, help="每品类最多扫描数(测试用)")
    parser.add_argument("--hide-threshold-chaos", type=float, default=None, help="隐藏阈值(混沌石): 不填则自动使用1D(神圣石)价格")
    parser.add_argument("--item-level-min", type=int, default=82, help="白装最低物品等级")
    parser.add_argument("--dry-run", action="store_true", help="只扫描不生成过滤器")
    args = parser.parse_args()

    # Ensure DB tables exist
    Base.metadata.create_all(bind=engine)

    categories = None
    if args.categories:
        categories = [c.strip() for c in args.categories.split(",")]

    t0 = time.time()

    # ── Step 1: Multi-category price scan ──
    logger.info("═══ Step 1: Multi-category price scan ═══")
    from app.services.price_scanner import scan_all_categories

    scan_report, _ = scan_all_categories(
        market=args.market,
        league=args.league,
        categories=categories,
        max_items_per_category=args.max_per_category,
    )
    logger.info(f"Scan done in {time.time() - t0:.1f}s: "
                f"{scan_report.priced}/{scan_report.total_items} priced, "
                f"{scan_report.errors} errors")

    if args.dry_run:
        logger.info("── dry-run mode, skipping filter generation ──")
        logger.info("Scan report: %s", scan_report.to_dict())
        return

    # ── Step 2: Generate price-aware filter ──
    t1 = time.time()
    logger.info("═══ Step 2: Generate price-aware filter ═══")
    from app.services.filter_generator import generate_from_latest_prices, _get_default_hide_threshold

    threshold = args.hide_threshold_chaos if args.hide_threshold_chaos is not None else _get_default_hide_threshold()
    result = generate_from_latest_prices(
        market=args.market,
        league=args.league,
        hide_threshold_chaos=threshold,
        item_level_min=args.item_level_min,
    )

    if result.get("error"):
        logger.error("Filter generation failed: %s", result["error"])
        sys.exit(1)

    logger.info(f"Filter generated in {time.time() - t1:.1f}s: {result['output_path']}")
    logger.info(f"  Total items: {result['total_count']}")
    logger.info(f"  Categories: {result['category_counts']}")
    logger.info(f"  Lines: {result['content_lines']}")

    # ── Step 3: Auto-copy to PoE2 directory ──
    t2 = time.time()
    poe2_dir = os.path.expanduser(
        os.path.join("~", "Documents", "My Games", "Path of Exile 2")
    )
    if os.path.isdir(poe2_dir) and result.get("output_path"):
        import shutil
        dest = os.path.join(poe2_dir, os.path.basename(result["output_path"]))
        shutil.copy2(result["output_path"], dest)
        logger.info(f"Copied filter to PoE2 directory: {dest}")
    else:
        logger.warning(f"PoE2 directory not found at {poe2_dir}, skipping auto-copy")

    total_time = time.time() - t0
    logger.info(f"═══ Daily filter update complete in {total_time:.1f}s ═══")


if __name__ == "__main__":
    main()
