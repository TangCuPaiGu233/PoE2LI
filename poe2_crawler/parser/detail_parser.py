"""Detail page parsers — extract relationships from individual entity pages."""
from __future__ import annotations

import re, logging
from bs4 import BeautifulSoup
from normalize.url_to_id import url_to_entity_id

logger = logging.getLogger(__name__)

LINK_RE = re.compile(r"^/(us|cn)/")
NAV = {"Items","Gem","Reforging","Unique_item","Modifiers","Skill_Gems","Support_Gems","Spirit_Gems","Lineage_Supports","Desecrated_Modifiers","Passive_skill","Keystone","Notable","Currency","Monster","Maps","Quest","Ascendancy","Character_class","Waystones","Keywords","NPCs","Flasks","Catalysts","Achievements","patreon"}


def parse_skill_detail(html: str, skill_entity_id: str) -> list[dict]:
    """Extract support gem relationships from a skill detail page.

    The 'Gems' section lists support gems compatible with this skill.
    Returns [{src_id, relation, dst_id, ...}] edges.
    """
    soup = BeautifulSoup(html, "lxml")
    edges: list[dict] = []
    seen: set[str] = set()

    for heading in soup.find_all(string=re.compile(r"^Gems$", re.I)):
        parent = heading.find_parent("div") or heading.find_parent("table")
        if not parent:
            continue
        for a in parent.find_all("a", href=LINK_RE):
            href = a["href"].split("#")[0]
            slug = href.rstrip("/").split("/")[-1]
            if slug in NAV:
                continue
            dst_id = url_to_entity_id(href, "support")
            key = (skill_entity_id, "supports", dst_id)
            if key in seen:
                continue
            seen.add(key)
            edges.append({
                "src_id": skill_entity_id,
                "relation": "supports",
                "dst_id": dst_id,
                "dst_name": a.get_text(strip=True),
            })
    return edges


def parse_unique_detail(html: str, unique_entity_id: str) -> list[dict]:
    """Extract unique→base relationship from a unique detail page.

    Base item is in <span class=\"lc\"> or <a class=\"whiteitem ...\">.
    """
    soup = BeautifulSoup(html, "lxml")
    edges: list[dict] = []

    # <a class="whiteitem Belt">Heavy Belt</a> — base type link
    a_tag = soup.find("a", class_=re.compile(r"whiteitem"))
    if a_tag:
        base_name = a_tag.get_text(strip=True)
        href = a_tag.get("href", "")
        if href and not href.startswith("#"):
            base_id = url_to_entity_id(href, "base_item")
        else:
            base_id = f"base_item:{base_name.replace(' ', '_')}"
        edges.append({
            "src_id": unique_entity_id,
            "relation": "based_on",
            "dst_id": base_id,
            "dst_name": base_name,
        })
    return edges


def parse_page_edges(html: str, entity_id: str, entity_type: str) -> list[dict]:
    """Route to the appropriate detail parser based on entity type."""
    if entity_type in ("skill",):
        return parse_skill_detail(html, entity_id)
    if entity_type in ("unique",):
        return parse_unique_detail(html, entity_id)
    return []
