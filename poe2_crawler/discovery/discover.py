"""Stage A: Entity URL discovery from poe2db index pages."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

from crawler.fetcher import Fetcher

logger = logging.getLogger(__name__)

with open("config/entity_types.yaml") as f:
    _CONFIG = yaml.safe_load(f)
with open("config/settings.yaml") as f:
    _SETTINGS = yaml.safe_load(f)

BASE_URL = _SETTINGS["base_url"]


def _crawl_index(fetcher: Fetcher, entity_type: str, spec: dict) -> list[dict]:
    """Scrape an index page to discover entity URLs and names."""
    results: list[dict] = []
    seen: set[str] = set()

    for index_url in spec.get("index_urls", []):
        full_url = index_url if index_url.startswith("http") else f"{BASE_URL}{index_url}"
        logger.info("Discovering %s from %s", entity_type, full_url)
        html = asyncio.run(fetcher.fetch(full_url))
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        prefix = spec.get("url_prefix", "/cn/")

        # Generic link extraction: find all <a> with href matching the prefix
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href.startswith(prefix) or href == prefix:
                continue
            # Skip fragment links, images, anchors
            if any(href.endswith(ext) for ext in (".png", ".jpg", ".gif", ".svg", ".css", ".js")):
                continue
            if "#" in href:
                href = href.split("#")[0]
            full = f"{BASE_URL}{href}" if not href.startswith("http") else href
            if full in seen:
                continue
            seen.add(full)

            name_cn = a.get_text(strip=True)
            # Try to extract name_en from href
            name_en = href.rstrip("/").split("/")[-1]

            results.append({
                "entity_type": entity_type,
                "url": full,
                "name_en": name_en,
                "name_cn": name_cn if name_cn else None,
            })
    return results


def discover_all(fetcher: Fetcher | None = None) -> dict[str, list[dict]]:
    """Discover all entity URLs across all configured types."""
    if fetcher is None:
        fetcher = Fetcher()
    all_results: dict[str, list[dict]] = {}
    for etype, spec in _CONFIG["entity_types"].items():
        results = _crawl_index(fetcher, etype, spec)
        all_results[etype] = results
        logger.info("Discovered %d %s entities", len(results), etype)

    # Save to file
    out_path = Path(_SETTINGS["entity_urls_file"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for etype, items in all_results.items():
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
    logger.info("Saved %d total entities to %s", sum(len(v) for v in all_results.values()), out_path)
    return all_results
