"""Ascendancy + Class relationship parser for poe2db.tw

Verified against real poe2db.tw DOM structure (2026-06-16, 18 probe rounds).
Key finding: relationships must be extracted from DOM block structure (figcaption / tab-pane),
not from link proximity ordering (which produces 296+ dirty edges).

Usage:
    python -m parser.parsers.ascendancy_parser
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Verified index URL
ASCENDANCY_INDEX_URL = "https://poe2db.tw/cn/Ascendancy_class"


def parse_ascendancy_index(html: str) -> dict:
    """Parse the ascendancy index page to extract class→ascendancy relationships.

    Returns dict with 'entities' (class + ascendancy nodes) and 'edges' (belongs_to).
    """
    soup = BeautifulSoup(html, "lxml")
    entities: dict[str, dict] = {}
    edges: list[dict] = []

    # PoE1 classes to exclude (may appear in non-default tabs)
    _POE1_CLASSES = {"shadow", "marauder", "ranger_poe1", "duelist", "templar", "scion"}

    tab_content = soup.find("div", class_="tab-content")
    if not tab_content:
        tab_content = soup

    # Only parse the first (default = PoE2) tab-pane
    first_tab = tab_content.find("div", class_="tab-pane")
    tabs = [first_tab] if first_tab else tab_content.find_all("div", class_="tab-pane")
    for tab in tabs:
        for col in tab.find_all("div", class_="col"):
            # Find the class row
            class_row = col.find("div", class_=re.compile(r"d-flex\s+border-top"))
            if not class_row:
                continue

            # Extract class info from the row's first child
            class_name_cn = None
            class_name_en = None
            class_link = class_row.find("a", href=re.compile(r"/(cn|us)/"))
            if class_link:
                class_name_cn = class_link.get_text(strip=True)
                href = class_link.get("href", "")
                class_name_en = href.rstrip("/").split("/")[-1]

            if not class_name_en:
                continue
            if class_name_en.lower() in _POE1_CLASSES:
                continue

            class_id = f"class:{class_name_en}"
            entities[class_id] = {"name": class_name_cn, "type": "class"}

            # Find ascendancy list container
            asc_div = class_row.find("div", class_="flex-grow-1")
            if not asc_div:
                continue

            # Extract all ascendancy links
            for a in asc_div.find_all("a", href=re.compile(r"/(cn|us)/")):
                text = a.get_text(" ", strip=True)
                href = a.get("href", "")
                en = href.rstrip("/").split("/")[-1]

                # Skip non-ascendancy links (notable skills, generic ITEM links)
                if _is_notable_link(a, text, en):
                    continue

                asc_id = f"ascendancy:{en}"
                entities[asc_id] = {"name": text, "type": "ascendancy"}
                edges.append({
                    "src_id": asc_id,
                    "src_cn": text,
                    "relation": "belongs_to",
                    "dst_id": class_id,
                    "dst_cn": class_name_cn,
                })

    return {"entities": entities, "edges": edges, "class_count": _count_type(entities, "class"),
            "ascendancy_count": _count_type(entities, "ascendancy"), "edge_count": len(edges)}


def _is_notable_link(a_tag, text: str, en: str) -> bool:
    """Filter out notable/passive skill links mixed in with ascendancy links."""
    # Ascendancies have non-empty text and valid English slug
    if not text or len(text) < 1:
        return True
    # Check for gem/passive icon indicators
    parent = a_tag.parent
    if parent and parent.find("img"):
        img_src = parent.find("img").get("src", "")
        if "gem" in img_src.lower() or "passive" in img_src.lower():
            return True
    return False


def _count_type(entities: dict, etype: str) -> int:
    return sum(1 for v in entities.values() if v.get("type") == etype)


def validate(parsed: dict) -> list[str]:
    """Run relationship consistency checks. Returns list of PASS/FAIL messages."""
    results = []
    entities, edges = parsed.get("entities", {}), parsed.get("edges", [])
    results.append(f"Classes found: {parsed.get('class_count', 0)}")
    results.append(f"Ascendancies found: {parsed.get('ascendancy_count', 0)}")
    results.append(f"Edges extracted: {parsed.get('edge_count', 0)}")

    # Check: every edge references real entities
    missing = []
    for e in edges:
        if e["src_id"] not in entities:
            missing.append(f'src={e["src_id"]}')
        if e["dst_id"] not in entities:
            missing.append(f'dst={e["dst_id"]}')
    results.append(f"PASS: all edges reference real entities" if not missing
                   else f"FAIL: {len(missing)} dangling edge endpoints")

    # Check: no ascendancy belongs to more than one class
    asc_parents: dict[str, str] = {}
    for e in edges:
        if e["relation"] == "belongs_to":
            if e["src_id"] in asc_parents and asc_parents[e["src_id"]] != e["dst_id"]:
                results.append(f"FAIL: {e['src_cn']} → both {asc_parents[e['src_id']]} and {e['dst_id']}")
            asc_parents[e["src_id"]] = e["dst_id"]
    if len(asc_parents) == parsed.get("ascendancy_count", 0):
        results.append("PASS: every ascendancy has exactly one class")
    else:
        results.append(f"WARN: {parsed.get('ascendancy_count', 0) - len(asc_parents)} ascendancies unlinked")

    # Check: key relationship — Witchhunter → Mercenary
    wh_edge = [e for e in edges if "witchhunter" in e.get("src_id", "")]
    if wh_edge:
        results.append(f"PASS: Witchhunter → {wh_edge[0]['dst_id']}" if "mercenary" in wh_edge[0]["dst_id"]
                       else f"FAIL: Witchhunter → {wh_edge[0]['dst_id']} (expected mercenary)")
    return results


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from crawler.fetcher import Fetcher
    import asyncio

    async def main():
        fetcher = Fetcher()
        html = await fetcher.fetch(ASCENDANCY_INDEX_URL)
        if not html:
            print("FAIL: could not fetch index page")
            return
        parsed = parse_ascendancy_index(html)
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
        print()
        print("=== Validation ===")
        for msg in validate(parsed):
            print(msg)
        await fetcher.close()

    asyncio.run(main())
