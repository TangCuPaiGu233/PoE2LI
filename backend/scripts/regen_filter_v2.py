"""Regenerate filter using poe.ninja economy data directly (no DB needed)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.poe_ninja_service import fetch_all_economy_prices
from app.services.filter_generator import (
    generate_filter_with_prices,
    _find_default_template,
    _get_default_hide_threshold,
)

OUTPUT_PATH = os.path.expandvars(
    r"%USERPROFILE%\Documents\My Games\Path of Exile 2"
    r"\asmco_4_endgame_AI价格过滤器.filter"
)

def main():
    # 1. Fetch all economy prices from poe.ninja
    print("Fetching poe.ninja economy data...")
    prices = fetch_all_economy_prices()
    print(f"  Total: {len(prices)} items\n")

    # Category breakdown
    from collections import Counter
    by_cat = Counter(p["category"] for p in prices)
    print("=== Category breakdown ===")
    for cat, count in sorted(by_cat.items()):
        print(f"  {cat:30s} {count:4d}")

    # 2. Count items at different thresholds
    threshold_1c = _get_default_hide_threshold()
    print(f"\n=== Hide counts at different thresholds (default = {threshold_1c:.1f}c) ===")
    for threshold in [0.04, 0.5, threshold_1c, threshold_1c * 8.5]:
        count = sum(1 for p in prices if p["chaos_price"] and 0 < p["chaos_price"] < threshold)
        label = f"{threshold:.2f}c".rstrip('0').rstrip('.')
        if abs(threshold - threshold_1c) < 0.01:
            label += " (1c)"
        elif abs(threshold - threshold_1c * 8.5) < 0.5:
            label += " (≈1D)"
        print(f"  <{label}: {count} items")

    # 3. Generate filter
    template_path = _find_default_template()
    print(f"\nTemplate: {template_path}")

    # Convert to snapshot format expected by generate_filter_with_prices
    snapshots = [
        {
            "name_en": p["name_en"],
            "name_cn": p["name_cn"] or "",
            "category": p["category"],
            "chaos_price": p["chaos_price"],
        }
        for p in prices
    ]

    result = generate_filter_with_prices(
        template_path=template_path,
        price_snapshots=snapshots,
        hide_threshold_chaos=threshold_1c,
        item_level_min=82,
        output_path=OUTPUT_PATH,
    )

    lines = result.split("\n")
    print(f"Output: {OUTPUT_PATH}")
    print(f"Total lines: {len(lines)}")

    # 4. Show generated hide blocks summary
    print("\n=== AI 智能隐藏 blocks ===")
    for i, line in enumerate(lines):
        if "[AI 智能隐藏]" in line or "低价" in line and "个" in line:
            print(f"  {i+1}: {line}")
        elif "Hide" == line.strip() and i > 0 and ("低价" in lines[i-1] or "低价" in lines[i-2] or "低价" in lines[i-3]):
            print(f"  {i+1}: {line}")

if __name__ == "__main__":
    main()
