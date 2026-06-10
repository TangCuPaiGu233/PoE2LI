"""scrape_caimogu_aliases.py — 从踩蘑菇社区 (poe2cn.caimogu.cc) 爬取国服中文译名。

数据对齐腾讯国服译名，覆盖：
  - 技能宝石：skills.html (SSR 渲染，~800+ 条)
  - 暗金装备：需要从各个分类页面爬取
  - 职业/升华：characters.html (SSR 渲染，已有 entity_dict)

输出 game_aliases_caimogu.json，可作为 CN↔EN 别名注入知识库。
"""
import re
import json
import sys
import time
import requests
from pathlib import Path

CAIMOGU_BASE = "https://poe2cn.caimogu.cc"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://poe2cn.caimogu.cc/",
}


def scrape_skills(output_dir: str) -> list[dict]:
    """Scrape CN↔EN skill gem names from skills.html (SSR-rendered)."""
    url = f"{CAIMOGU_BASE}/skills.html"
    print(f"Scraping skills: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    text = resp.text

    # Pattern: <a href=".../p/NAME.html" class="skill-name...">CN_TEXT</a>
    pattern = (
        r'<a[^>]*href=["\'](?:https://poe2cn\.caimogu\.cc)?/p/([^"\']+)\.html["\']'
        r'[^>]*class="skill-name[^>]*>(.*?)</a>'
    )
    matches = re.findall(pattern, text)
    print(f"  Found {len(matches)} skill links")

    skills = []
    for en_slug, cn_html in matches:
        cn_name = re.sub(r'<[^>]+>', '', cn_html).strip()
        if cn_name and en_slug and not en_slug.startswith("/"):
            skills.append({
                "cn": cn_name,
                "en": en_slug.replace("_", " "),
                "type": "skill",
                "source": "caimogu",
            })

    # Save
    out_path = Path(output_dir) / "skills_cn.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(skills, f, ensure_ascii=False, indent=2)
    print(f"  Saved {len(skills)} skills → {out_path}")
    return skills


def scrape_uniques(output_dir: str) -> list[dict]:
    """Scrape unique items CN names from item detail pages.

    Strategy: the skills page had all skills on one page. For items,
    we need to find the unique listing page. Try /uniques or /items pages.
    """
    items = []

    # Try the main items listing pages by type
    item_types = [
        "weapon", "armour", "accessory", "jewellery",
        "one_hand_weapon", "two_hand_weapon", "body_armour",
        "helmet", "boots", "gloves", "shield", "quiver",
        "ring", "amulet", "belt", "flask", "jewel",
    ]

    for itype in item_types:
        try:
            url = f"{CAIMOGU_BASE}/items/{itype}.html"
            print(f"  Trying {url}...")
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code != 200:
                print(f"    → {resp.status_code}, skip")
                continue

            text = resp.text
            # Same pattern as skills
            pattern = (
                r'<a[^>]*href=["\'](?:https://poe2cn\.caimogu\.cc)?/p/([^"\']+)\.html["\']'
                r'[^>]*class="(?:skill-name|item-name)[^>]*>(.*?)</a>'
            )
            matches = re.findall(pattern, text)
            print(f"    Found {len(matches)} links")
            for en_slug, cn_html in matches:
                cn_name = re.sub(r'<[^>]+>', '', cn_html).strip()
                if cn_name and en_slug:
                    items.append({
                        "cn": cn_name,
                        "en": en_slug.replace("_", " "),
                        "type": "item",
                        "source": "caimogu",
                    })
            time.sleep(0.5)
        except Exception as e:
            print(f"    Error: {e}")

    if items:
        out_path = Path(output_dir) / "items_cn.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print(f"  Saved {len(items)} items → {out_path}")

    return items


def scrape_all(output_dir: str = "."):
    """Scrape all available CN→EN mappings from caimogu."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    all_aliases = []

    # Skills
    skills = scrape_skills(output_dir)
    all_aliases.extend(skills)

    # Unique items
    uniques = scrape_uniques(output_dir)
    all_aliases.extend(uniques)

    # Combined output
    combined_path = Path(output_dir) / "game_aliases_caimogu.json"
    output = {
        "cn_to_en": {a["cn"]: {"en": a["en"], "type": a["type"]} for a in all_aliases},
        "total": len(all_aliases),
        "source": "caimogu (Tencent-aligned CN translations)",
    }
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nTotal: {len(all_aliases)} CN→EN mappings → {combined_path}")
    return all_aliases


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/app/data/caimogu_aliases"
    scrape_all(out)
