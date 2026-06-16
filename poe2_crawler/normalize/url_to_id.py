"""URL → canonical entity_id mapping."""
from __future__ import annotations

import re


def url_to_entity_id(url: str, entity_type: str) -> str:
    """Convert a poe2db URL to a canonical entity_id.

    Examples:
        /cn/Ascendancy_class/Witchhunter  → ascendancy:witchhunter
        /cn/Skill_Gems/Lightning_Arrow    → skill:lightning_arrow
    """
    slug = url.rstrip("/").split("/")[-1]
    slug = re.sub(r"[^\w\-]+", "_", slug).strip("_").lower()
    return f"{entity_type}:{slug}"


def entity_id_to_kb_key(entity_id: str) -> str:
    """Convert entity_id to kb_entities.entity_key format."""
    return entity_id.replace(":", "_", 1)
