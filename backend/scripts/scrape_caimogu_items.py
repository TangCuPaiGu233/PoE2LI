"""scrape_caimogu_items.py — 从踩蘑菇抓取暗金物品国服中文译名。

策略：
  1. 从 knowledge_chunks 提取 poe2db 物品的英文名（用作 URL slug）
  2. 逐页抓取 https://poe2cn.caimogu.cc/p/{EN_NAME}.html
  3. 从 <title> 标签提取 CN 名（格式: "CN名 物品类型 - ..."）
  4. 保存 game_aliases_caimogu_items.json
"""
import json
import re
import sys
import os
import time

import requests

CAIMOGU_BASE = "https://poe2cn.caimogu.cc"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://poe2cn.caimogu.cc/",
}

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk


def get_item_slugs() -> list[str]:
    """Extract unique English item names from poe2db item chunks."""
    db = SessionLocal()
    try:
        chunks = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.source == "poe2db",
            KnowledgeChunk.chunk_type == "item"
        ).all()
        names = set()
        for c in chunks:
            try:
                data = json.loads(c.content)
                path = data.get("detail_path", "")
                if path:
                    names.add(path)
                else:
                    name_en = data.get("name_en", "")
                    if name_en:
                        names.add(name_en)
            except Exception:
                pass
        db.close()
        return sorted(names)
    finally:
        db.close()


def scrape_item_page(slug: str) -> dict | None:
    """Fetch a caimogu item page and extract CN name."""
    url = f"{CAIMOGU_BASE}/p/{slug}.html"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        text = resp.text

        # Extract CN name from <title>: "CN名 物品类型 - ..."
        title_match = re.search(r"<title>([^<]+)</title>", text)
        if not title_match:
            return None
        title = title_match.group(1)
        # Split: "猎首 重革腰带 - 流放之路：降临资料站 ..."
        parts = title.split(" - ")
        name_part = parts[0].strip() if parts else title
        # First part is "CN名 物品类型" — take first word group
        # Actually split by space to get just the CN name
        name_words = name_part.split()
        if len(name_words) >= 2:
            cn_name = name_words[0]  # First word is the CN name
        else:
            cn_name = name_part

        return {"cn": cn_name, "en": slug, "source": "caimogu", "type": "item"}
    except Exception as e:
        return None


def scrape_all(output_dir: str = "/app/data"):
    """Main: extract slugs → scrape pages → save aliases."""
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "caimogu_items.json")

    # Resume support
    existing = {}
    if os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            existing = {item["en"]: item for item in json.load(f)}
        print(f"Resume: {len(existing)} already scraped")

    slugs = get_item_slugs()
    print(f"Total poe2db item slugs: {len(slugs)}")

    pending = [s for s in slugs if s not in existing]
    print(f"Pending: {len(pending)}")

    items = list(existing.values())
    for i, slug in enumerate(pending):
        result = scrape_item_page(slug)
        if result:
            items.append(result)
            if (i + 1) % 20 == 0:
                _save(items, output_path)
                print(f"  [{i+1}/{len(pending)}] {len(items)} items")
        time.sleep(0.5)  # Rate limit

    _save(items, output_path)
    print(f"\nDone: {len(items)} items → {output_path}")
    return items


def _save(items, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/app/data"
    scrape_all(out)
