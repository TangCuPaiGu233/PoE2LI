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


def get_item_slugs() -> list[tuple[str, str]]:
    """Extract (en_name, slug) pairs from poe2db item chunks.

    Returns list of (name_en, url_slug).
    Filters out index pages (Skill Gems, Support Gems, etc.)
    """
    NON_ITEMS = {
        "skill gems", "support gems", "spirit gems", "lineage supports",
        "desecrated modifiers", "keywords", "crafting", "quest",
        "ascendancy classes", "act", "waystones", "patreon",
        "modifiers", "unique item", "items",
    }
    db = SessionLocal()
    try:
        chunks = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.source == "poe2db",
            KnowledgeChunk.chunk_type == "item"
        ).all()
        pairs = []
        for c in chunks:
            try:
                data = json.loads(c.content)
                name_en = data.get("name_en", "").strip()
                if not name_en or name_en.lower() in NON_ITEMS:
                    continue
                # name_en may contain item name + base type concatenated
                # e.g., "Sands of SilkShrouded Vest" → extract "Sands of Silk"
                # Check if cn_data has a proper name
                slug = _name_to_slug(name_en)
                if slug:
                    pairs.append((name_en, slug))
            except Exception:
                pass
        db.close()
        # Dedup by slug
        seen = set()
        unique = []
        for name_en, slug in pairs:
            if slug not in seen:
                seen.add(slug)
                unique.append((name_en, slug))
        return unique
    finally:
        db.close()


def _name_to_slug(name_en: str) -> str:
    """Convert an English item name to a caimogu URL slug.

    Caimogu uses the item name with spaces and apostrophes preserved,
    special chars stripped. e.g., "Atziri's Disdain" → "Atziris_Disdain"
    """
    import re
    # Remove base type concatenation: split on uppercase following lowercase
    # "Sands of SilkShrouded Vest" → first part before a lowercase→UPPERCASE boundary
    # that follows a non-space
    slug = re.sub(r"([a-z])([A-Z])", lambda m: m.group(1) + " " + m.group(2), name_en)
    # Take first part if name seems to have base type appended
    # Heuristic: if >3 words, the last 1-2 words might be base type
    words = slug.split()
    if len(words) > 3:
        # Common base types to strip
        base_types = {
            "vest", "robe", "circlet", "belt", "ring", "amulet", "boots",
            "gloves", "gauntlets", "helm", "helmet", "shield",
            "sword", "axe", "mace", "bow", "wand", "sceptre", "staff",
            "spear", "crossbow", "quiver", "flask", "jewel",
            "cuisses", "greaves", "sollerets", "coat", "mail", "plate",
            "mask", "crown", "hood", "shroud", "sash", "talisman",
            "spirit", "diamond", "pearl", "coral",
        }
        # Strip trailing base type words
        while len(words) > 1 and words[-1].lower() in base_types:
            words = words[:-1]
        slug = " ".join(words)
    return slug.replace(" ", "_").replace("'", "").replace('"', "").replace(".", "")


def scrape_item_page(slug: str) -> dict | None:
    """Fetch a caimogu item page and extract CN name."""
    url = f"{CAIMOGU_BASE}/p/{slug}.html"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        text = resp.text

        # Check for "page not found" pattern
        if "页面不存在" in text or len(text) < 5000:
            return None

        # Extract CN name from <title>: "CN名 物品类型 - 流放之路：降临资料站 ..."
        title_match = re.search(r"<title>([^<]+)</title>", text)
        if not title_match:
            return None
        title = title_match.group(1)

        # Skip pages where the title starts with site name (invalid/missing item)
        if title.startswith("流放之路") or title.startswith("踩蘑菇"):
            return None

        # Split: "猎首 重革腰带 - 流放之路：降临资料站 ..."
        parts = title.split(" - ")
        name_part = parts[0].strip() if parts else title

        # "猎首 重革腰带" → CN name = "猎首", base type = "重革腰带"
        name_words = name_part.split()
        if len(name_words) >= 2:
            cn_name = name_words[0]
            base_type = name_words[1]
        else:
            cn_name = name_part
            base_type = ""

        # Validate: CN name should contain CJK characters
        if not re.search(r'[一-鿿]', cn_name):
            return None

        return {
            "cn": cn_name,
            "en": slug,
            "base_type": base_type,
            "source": "caimogu",
            "type": "item",
        }
    except Exception:
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

    pending = [(name_en, slug) for name_en, slug in slugs if slug not in existing]
    print(f"Pending: {len(pending)}")

    items = list(existing.values())
    for i, (name_en, slug) in enumerate(pending):
        result = scrape_item_page(slug)
        if result:
            result["name_en_raw"] = name_en
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
