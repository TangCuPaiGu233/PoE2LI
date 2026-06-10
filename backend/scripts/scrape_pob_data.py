"""Scrape PoB repository data via jsDelivr CDN.

P0 sources:
  - tree.json (1.9MB) → 4912 passive tree nodes
  - Bases/*.lua (28 files) → all base items with implicits
  - Gems.lua (513KB) → all skill + support gems
  - ModItem.lua (1MB) → item mod pools with roll ranges
  - Minions.lua (44KB) → summon data

All served via CDN, no rate limits, no auth required.
"""

import urllib.request
import json, re, sys, os, time, logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger('pob')

CDN = "https://cdn.jsdelivr.net/gh/PathOfBuildingCommunity/PathOfBuilding-PoE2@dev"

# Base item files to scrape
BASE_FILES = [
    "amulet", "axe", "belt", "body", "boots", "bow", "claw", "crossbow",
    "dagger", "flail", "flask", "focus", "gloves", "helmet", "jewel",
    "mace", "quiver", "ring", "sceptre", "shield", "spear", "staff",
    "sword", "talisman", "traptool", "wand",
]

def fetch(path):
    url = f"{CDN}/{path}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'PoE2LI/1.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        logger.error(f"Fetch {path}: {e}")
        return None


def parse_tree_json(text):
    """Parse tree.json → extract passive nodes with name, stats, class."""
    data = json.loads(text)
    chunks = []
    nodes = data.get("nodes", {})

    for node_id, node in nodes.items():
        name = node.get("name", "")
        stats = node.get("stats", [])
        ascendancy = node.get("ascendancyName", "")
        is_notable = node.get("isNotable", False)
        is_keystone = node.get("isKeystone", False)
        is_ascendancy = node.get("isAscendancyStart", False)
        flavour = node.get("flavourText", [])
        if isinstance(flavour, list):
            flavour = " ".join(flavour)

        # Build search text
        parts = [f"Passive: {name}"]
        if ascendancy:
            parts.append(f"Ascendancy: {ascendancy}")
        if stats:
            parts.append("Stats: " + "; ".join(stats))
        if flavour:
            parts.append(flavour)

        node_type = "keystone" if is_keystone else "notable" if is_notable else "ascendancy" if is_ascendancy else "passive"

        chunks.append({
            "chunk_id": f"tree_{node_id}",
            "content_type": "passive",
            "source_page": "PoB_tree",
            "node_id": node_id,
            "name": name,
            "ascendancy": ascendancy,
            "node_type": node_type,
            "stats": stats,
            "search_text": "\n".join(parts)[:3000],
        })

    logger.info(f"Tree: {len(chunks)} passive nodes ({sum(1 for c in chunks if c['node_type']!='passive')} special)")
    return chunks


def parse_lua_items(text, category):
    """Parse Bases/*.lua → extract base items with implicits."""
    chunks = []
    # Pattern: itemBases["Name"] = { type = "...", ... implicit = "..." ... }
    pattern = re.compile(
        r'itemBases\["([^"]+)"\]\s*=\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}',
        re.DOTALL
    )

    for match in pattern.finditer(text):
        name = match.group(1)
        body = match.group(2)

        item_type = ""
        implicit = ""
        tags = []

        type_match = re.search(r'type\s*=\s*"([^"]+)"', body)
        if type_match:
            item_type = type_match.group(1)

        imp_match = re.search(r'implicit\s*=\s*"([^"]+)"', body)
        if imp_match:
            implicit = imp_match.group(1)

        tag_match = re.search(r'tags\s*=\s*\{([^}]+)\}', body)
        if tag_match:
            tags = re.findall(r'(\w+)\s*=\s*true', tag_match.group(1))

        search_text = f"[{category}] {name}"
        if item_type:
            search_text += f" | Type: {item_type}"
        if implicit:
            search_text += f" | Implicit: {implicit}"
        if tags:
            search_text += f" | Tags: {', '.join(tags)}"

        chunks.append({
            "chunk_id": f"base_{name.replace(' ','_')}",
            "content_type": "item",
            "source_page": "PoB_Bases",
            "name": name,
            "item_type": item_type,
            "category": category,
            "implicit": implicit,
            "tags": tags,
            "search_text": search_text[:2000],
        })

    return chunks


def parse_lua_gems(text):
    """Parse Gems.lua → extract skill and support gems."""
    chunks = []
    # Pattern: ["Metadata/Items/Gems/..."] = { name = "...", ... }
    pattern = re.compile(
        r'\["([^"]+)"\]\s*=\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}',
        re.DOTALL
    )

    for match in pattern.finditer(text):
        gem_id = match.group(1)
        body = match.group(2)

        name = ""
        base_type = ""
        gem_tags = ""

        name_match = re.search(r'name\s*=\s*"([^"]+)"', body)
        if name_match:
            name = name_match.group(1)

        type_match = re.search(r'baseTypeName\s*=\s*"([^"]+)"', body)
        if type_match:
            base_type = type_match.group(1)

        tags_match = re.search(r'gemTags\s*=\s*\{([^}]+)\}', body)
        if tags_match:
            gem_tags = tags_match.group(1).strip()

        is_support = "Support" in gem_id or "Support" in gem_tags

        search_text = f"{'Support' if is_support else 'Skill'} Gem: {name}"
        if base_type and base_type != name:
            search_text += f" ({base_type})"
        if gem_tags:
            search_text += f" | Tags: {gem_tags}"

        chunks.append({
            "chunk_id": f"gem_{name.replace(' ','_')}",
            "content_type": "gem",
            "source_page": "PoB_Gems",
            "name": name,
            "gem_type": "support" if is_support else "skill",
            "gem_tags": gem_tags,
            "search_text": search_text[:2000],
        })

    logger.info(f"Gems: {len(chunks)} parsed")
    return chunks


def parse_lua_mods(text):
    """Parse ModItem.lua → extract item mod pools."""
    chunks = []
    # Each mod entry has name, mod type, spawn weight, stats
    pattern = re.compile(
        r'\["([^"]+)"\]\s*=\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}',
        re.DOTALL
    )

    for match in pattern.finditer(text):
        mod_id = match.group(1)
        body = match.group(2)

        name = ""
        mod_type = ""

        name_match = re.search(r'name\s*=\s*"([^"]+)"', body)
        if name_match:
            name = name_match.group(1)

        type_match = re.search(r'type\s*=\s*"([^"]+)"', body)
        if type_match:
            mod_type = type_match.group(1)

        # Extract stat keys
        stats = re.findall(r'"([^"]+)"', body)
        stat_text = "; ".join(stats[:5])

        search_text = f"Mod: {name}"
        if mod_type:
            search_text += f" | Type: {mod_type}"
        if stat_text:
            search_text += f" | Stats: {stat_text}"

        chunks.append({
            "chunk_id": f"mod_{mod_id.replace('/','_')[:60]}",
            "content_type": "mod",
            "source_page": "PoB_ModItem",
            "name": name,
            "mod_type": mod_type,
            "search_text": search_text[:2000],
        })

    logger.info(f"Mods: {len(chunks)} parsed")
    return chunks


def scrape():
    all_chunks = []

    # 1. Tree
    logger.info("=== Tree ===")
    text = fetch("src/TreeData/0_5/tree.json")
    if text:
        chunks = parse_tree_json(text)
        all_chunks.extend(chunks)

    # 2. Base items
    logger.info("=== Bases ===")
    for bf in BASE_FILES:
        text = fetch(f"src/Data/Bases/{bf}.lua")
        if text:
            chunks = parse_lua_items(text, bf)
            all_chunks.extend(chunks)
            logger.info(f"  {bf}: {len(chunks)} items")
        time.sleep(0.5)

    # 3. Gems
    logger.info("=== Gems ===")
    text = fetch("src/Data/Gems.lua")
    if text:
        chunks = parse_lua_gems(text)
        all_chunks.extend(chunks)

    # 4. Mods
    logger.info("=== Mods ===")
    text = fetch("src/Data/ModItem.lua")
    if text:
        chunks = parse_lua_mods(text)
        all_chunks.extend(chunks)

    # 5. Minions
    logger.info("=== Minions ===")
    text = fetch("src/Data/Minions.lua")
    if text:
        # Simple parse: extract minion names and tags
        for match in re.finditer(r'\["([^"]+)"\]\s*=\s*\{([^}]+)\}', text, re.DOTALL):
            name = match.group(1)
            body = match.group(2)
            tags = re.findall(r'(\w+)\s*=\s*true', body)
            all_chunks.append({
                "chunk_id": f"minion_{name.replace('/','_')[:60]}",
                "content_type": "minion",
                "source_page": "PoB_Minions",
                "name": name,
                "tags": tags,
                "search_text": f"Minion: {name} | Tags: {', '.join(tags)}",
            })
        logger.info(f"Minions: {len([c for c in all_chunks if c['content_type']=='minion'])} parsed")

    # Save
    out = sys.argv[1] if len(sys.argv) > 1 else "pob_data.jsonl"
    with open(out, 'w', encoding='utf-8') as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + '\n')

    # Stats
    types = {}
    for c in all_chunks:
        t = c['content_type']
        types[t] = types.get(t, 0) + 1

    logger.info(f"\nDone: {len(all_chunks)} total chunks")
    for t, n in sorted(types.items()):
        logger.info(f"  {t}: {n}")


if __name__ == "__main__":
    scrape()
