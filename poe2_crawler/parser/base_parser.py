"""Base parser for poe2db index pages with tab-pane structure."""
from __future__ import annotations

import re
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Navigation links to exclude from entity extraction
_NAV_PATTERNS = [
    "Items", "Gem", "Reforging", "Passive_skill", "Passive_Skill",
    "Currency", "Unique_item", "Keystone", "Notable", "Monster", "Area",
    "Quest", "Ascendancy", "Character_class", "Skill_Gems", "Support_Gems",
    "Spirit_Gems", "Modifiers", "Gem_Tags", "Crafting", "Flask",
    "Lineage_Supports", "Keywords", "Act", "patreon", "atlas-skill-tree",
    "passive-skill-tree", "EndGame", "Hideout", "Liquid_Emotions",
    "Maps", "Waystones", "NPCs", "Flasks", "Catalysts", "Achievements",
    "MicrotransactionCombineFormula", "MinimapIcons", "Miscellaneous",
    "Consumable", "Splinter", "Strongbox", "GameConstants", "Commands",
    "HelpfulTips", "QuestRewards",
]


def _is_nav_link(href: str) -> bool:
    return any(n.lower() in href.lower() for n in _NAV_PATTERNS)


def parse_entity_list(html: str, entity_type: str, poe2_tab_only: bool = True) -> dict:
    """Parse a tab-pane index page to extract entities.

    Most poe2db pages have 4 tabs: Tab 0=PoE2, Tab 1=PoE2(alt), Tab 2=PoE1, Tab 3=empty.
    For PoE2LI we only want Tab 0.

    Returns {entities: {entity_id: {name, type}}, raw_edges: []}
    """
    soup = BeautifulSoup(html, "lxml")
    entities: dict[str, dict] = {}
    seen_hrefs: set[str] = set()

    tabs = soup.find_all("div", class_="tab-pane")
    tabs_to_parse = tabs[:1] if (poe2_tab_only and tabs) else tabs

    if not tabs_to_parse or all(len(tab.find_all("a", href=re.compile(r"^/cn/"))) == 0 for tab in tabs_to_parse):
        tabs_to_parse = [soup]  # fallback: whole page (entity links outside tabs)

    for tab in tabs_to_parse:
        for a_tag in tab.find_all("a", href=re.compile(r"^/cn/")):
            href = a_tag["href"].split("#")[0]
            if href == "/cn/":
                continue
            if _is_nav_link(href):
                continue

            text = a_tag.get_text(" ", strip=True)
            en = href.rstrip("/").split("/")[-1]
            eid = f"{entity_type}:{en}"

            if href in seen_hrefs:
                # We already saw this entity — update name if we now have text and didn't before
                if text and eid in entities and not entities[eid].get("name"):
                    entities[eid]["name"] = text
                continue
            seen_hrefs.add(href)
            entities[eid] = {"name": text, "type": entity_type}

    logger.info("Parsed %d %s entities from %d links", len(entities), entity_type, len(seen_hrefs))
    return {"entities": entities, "raw_edges": []}
