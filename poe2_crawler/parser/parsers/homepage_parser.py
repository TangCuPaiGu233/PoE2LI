"""Homepage parser — discovers ALL linked content pages from /cn/ navigation.

Unlike tab-pane index pages, the homepage is a flat link directory.
Every link leads to a content page covering a game mechanic, boss, keyword, etc.
"""
from __future__ import annotations

import re
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Pages we already cover via dedicated index pages — don't duplicate
_ALREADY_COVERED = {
    "Skill_Gems", "Support_Gems", "Spirit_Gems", "Unique_item",
    "Ascendancy_class", "Character_class", "Modifiers",
    "Passive_skill", "Keystone", "Notable", "Currency",
    "Monster", "Maps", "Quest", "Crafting",
    "Gem", "Items", "Keywords", "NPCs",
    "Flasks", "Catalysts", "Achievements",
}

# Navigation/utility pages to exclude
_EXCLUDE = {
    "patreon", "passive-skill-tree", "atlas-skill-tree",
    "MicrotransactionCombineFormula", "MinimapIcons",
    "Reforging_Bench", "Hideout", "FlavourText",
    # Supporters/cosmetics
    "Closed_Beta_Supporter_Packs", "Open_Beta_Supporter_Packs",
    "Release_Supporter_Packs", "Race_Rewards",
    "Core_2021", "Core_2022", "Core_2023", "Core_2024",
}

# URL pattern → entity_type mapping
_PATTERN_TYPE = {
    "league": "league_mechanic",
    "version": "patch_note",
    "act": "area",
}


def parse_homepage(html: str) -> dict:
    """Parse homepage to discover all content pages."""
    soup = BeautifulSoup(html, "lxml")
    entities: dict[str, dict] = {}
    seen: set[str] = set()

    for a in soup.find_all("a", href=re.compile(r"^/cn/")):
        href = a["href"].split("#")[0].split("?")[0].rstrip("/")
        if href == "/cn":
            continue
        if href in seen:
            continue
        seen.add(href)

        slug = href.split("/")[-1]
        text = a.get_text(" ", strip=True)

        # Skip already-covered index pages
        if slug in _ALREADY_COVERED:
            continue
        if any(slug.startswith(p) for p in _EXCLUDE):
            continue

        # Determine entity type from URL pattern
        slug_lower = slug.lower()
        if "_league" in slug_lower or "league" in slug_lower:
            etype = "league_mechanic"
        elif slug_lower.startswith("version_"):
            etype = "patch_note"
        elif slug_lower.startswith("act_"):
            etype = "area"
        elif "_" not in slug or slug[0].isupper():
            # Single words with no underscore are likely mechanics/keywords (e.g. "Breach", "Fire")
            etype = "game_mechanic"
        else:
            etype = "other"

        eid = f"{etype}:{slug}"
        entities[eid] = {"name": text, "type": etype}

    logger.info("Homepage discovery: %d entities from %d links", len(entities), len(seen))
    return {"entities": entities, "raw_edges": []}
