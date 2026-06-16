"""Probe all verified index pages to map DOM structures for parser writing."""
import asyncio, sys, json, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from crawler.fetcher import Fetcher
from bs4 import BeautifulSoup

PAGES = {
    "skill": "https://poe2db.tw/cn/Skill_Gems",
    "support": "https://poe2db.tw/cn/Support_Gems",
    "spirit_gem": "https://poe2db.tw/cn/Spirit_Gems",
    "unique": "https://poe2db.tw/cn/Unique_item",
    "base_item": "https://poe2db.tw/cn/Item",
    "mod": "https://poe2db.tw/cn/Modifiers",
    "passive": "https://poe2db.tw/cn/Passive_skill",
    "currency": "https://poe2db.tw/cn/Currency",
    "monster": "https://poe2db.tw/cn/Monster",
    "area": "https://poe2db.tw/cn/Area",
}

async def probe(name: str, url: str, fetcher: Fetcher):
    html = await fetcher.fetch(url)
    if not html:
        print(f"{name}: FAIL (no response)")
        return None
    soup = BeautifulSoup(html, "lxml")

    # Key findings
    result = {"name": name, "url": url, "size": len(html)}

    # Find main content area
    for content_id in ["mw-content-text", "bodyContent", "main"]:
        c = soup.find(id=content_id)
        if c:
            result["main_container"] = content_id
            break

    # Find entity links pattern
    links = []
    for a_tag in soup.find_all("a", href=re.compile(r"^/cn/")):
        href = a_tag["href"]
        if any(skip in href.lower() for skip in ["/cn/#", "/cn/api", "/cn/special", "/cn/index"]):
            continue
        links.append({"href": href, "text": a_tag.get_text(strip=True)[:60]})
    result["link_count"] = len(links)
    result["links_sample"] = links[:15]

    # Find structural elements
    for selector in ["table.wikitable", "table.sortable", "div.item-list", "div.gem-list",
                      "ul.gem-list", "div.responsive-table", "table.item-table"]:
        el = soup.select(selector)
        if el:
            result[f"has_{selector.replace('.','_').replace('-','_')}"] = len(el)

    # Check for tab-pane structure (like ascendancy page)
    tabs = soup.find_all("div", class_="tab-pane")
    result["tab_count"] = len(tabs)

    print(f"{name}: {len(html)} bytes, {len(links)} links, {len(tabs)} tabs")
    return result


async def main():
    fetcher = Fetcher()
    results = {}
    for name, url in PAGES.items():
        r = await probe(name, url, fetcher)
        if r:
            results[name] = r
    await fetcher.close()

    # Save results
    out = Path("data/page_probes.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved to {out}")

    # Summary
    for name, r in results.items():
        print(f"\n{name}: {r['link_count']} links, tabs={r['tab_count']}")
        sample_types = set()
        for l in r.get("links_sample", []):
            href = l["href"]
            if "/" in href.split("?")[0].rstrip("/").split("/")[-1]:
                sample_types.add(href.split("?")[0].rstrip("/").split("/")[-2])
        if sample_types:
            print(f"  URL pattern samples: {list(sample_types)[:5]}")

if __name__ == "__main__":
    asyncio.run(main())
