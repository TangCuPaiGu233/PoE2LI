"""Stat→ItemType availability validation for PoE2 Trade Search.

Ensures stat IDs resolved via vector search actually exist on the target
item type before building the Trade API query. Uses heuristic pattern
rules based on empirical PoE2 Trade API testing.

Problem: LLM generates stat descriptions → vector search finds closest
stat ID → but that stat might not ROLL on the target item type.
This is the #1 cause of 0-result searches.

Solution: After vector resolution, filter stats against include/exclude
patterns for the target item type. Also provides universal fallback stats
that exist on all item types.
"""

import re
import logging

logger = logging.getLogger(__name__)

# ── Universal stats (roll on ALL equipment types) ──
# These are injected as fallback when count groups lose too many stats
UNIVERSAL_INCLUDE = [
    r"\+# to maximum Life",
    r"\+#% to Fire Resistance",
    r"\+#% to Cold Resistance",
    r"\+#% to Lightning Resistance",
    r"\+#% to Chaos Resistance",
    r"\+# to maximum Energy Shield",
]

# ── Availability rules per item category ──
# include: stat must match at least ONE pattern (if empty, allow all)
# exclude: stat must NOT match any pattern (always checked first)
# Rules are regex patterns matched against stat ref_text

STAT_AVAILABILITY = {
    "accessory.amulet": {
        "include": [
            r"to Spirit\b",                           # # to Spirit (flat)
            r"Level of all Minion Skills",            # +minion gems
            r"Level of all Spell Skills",             # +spell gems
            r"to maximum Life",
            r"to maximum Energy Shield",
            r"to maximum Mana",
            r"Fire Resistance",
            r"Cold Resistance",
            r"Lightning Resistance",
            r"Chaos Resistance",
            r"all Elemental Resistances",
            r"increased Cast Speed",
            r"increased Rarity of Items",
            r"to (Strength|Dexterity|Intelligence|all Attributes)",
            r"Allies in your Presence have.*(?:Attack Speed|Cast Speed|Critical)",
            r"Life Regeneration",
            r"Mana Regeneration",
        ],
        "exclude": [
            r"Minions deal",
            r"Minions have",
            r"Minions gain",
            r"Minions (take|Leech|Regenerate|Recover|Convert)",
            # NOTE: DO NOT use r"Minion" alone — it catches "Level of all Minion Skills"!
            r"Allies in your Presence deal.*added.*Damage",  # damage auras = weapon only
            r"Allies in your Presence deal.*increased Damage",
            r"Allies.*all Elemental Resistances",
            r"increased Spirit",                       # %Spirit not on amulet
            r"to Level of all (?!Minion|Spell)",       # non-minion/spell gem levels
        ],
    },
    "accessory.ring": {
        "include": [
            r"to maximum Life",
            r"to maximum Energy Shield",
            r"to maximum Mana",
            r"Fire Resistance",
            r"Cold Resistance",
            r"Lightning Resistance",
            r"Chaos Resistance",
            r"all Elemental Resistances",
            r"to (Strength|Dexterity|Intelligence|all Attributes)",
            r"increased Rarity of Items",
            r"Mana Regeneration",
            r"Life Regeneration",
            r"increased Cast Speed",
            r"increased Attack Speed",
            r"Physical Damage.*Attacks",
            r"added.*Damage.*Attacks",
        ],
        "exclude": [
            r"Spirit",
            r"Minion",
            r"Allies",
            r"to Level of all",
            r"Aura",
            r"Totem",
        ],
    },
    "accessory.belt": {
        "include": [
            r"to maximum Life",
            r"to maximum Mana",
            r"Fire Resistance",
            r"Cold Resistance",
            r"Lightning Resistance",
            r"Chaos Resistance",
            r"to (Strength|Dexterity|Intelligence|all Attributes)",
            r"Flask",
            r"Life Regeneration",
        ],
        "exclude": [
            r"Spirit",
            r"Minion",
            r"Allies",
            r"to Level of all",
            r"Energy Shield",
            r"Cast Speed",
            r"Attack Speed",
        ],
    },
    "weapon.sceptre": {
        "include": [
            r"Minions deal",
            r"Minions have",
            r"Minions gain",
            r"Allies in your Presence deal",
            r"Allies in your Presence have",
            r"to Spirit",
            r"increased Spirit",
            r"Level of all Minion",
            r"Level of all Spell",
            r"increased Cast Speed",
            r"increased Attack Speed",
            r"Fire Damage",
            r"Cold Damage",
            r"Lightning Damage",
            r"Chaos Damage",
            r"Physical Damage",
            r"increased Damage",
            r"Critical",
            r"to (Strength|Dexterity|Intelligence|all Attributes)",
        ],
        "exclude": [
            r"to maximum Life",
            r"to maximum Energy Shield",
            r"Fire Resistance",
            r"Cold Resistance",
            r"Lightning Resistance",
            r"Chaos Resistance",
            r"Rarity of Items",
        ],
    },
    "weapon.wand": {
        "include": [
            r"Level of all Spell",
            r"increased Spell Damage",
            r"increased Cast Speed",
            r"added.*Damage",
            r"Fire Damage",
            r"Cold Damage",
            r"Lightning Damage",
            r"Chaos Damage",
            r"Critical",
            r"to (Strength|Dexterity|Intelligence|all Attributes)",
            r"Mana Regeneration",
        ],
        "exclude": [
            r"to maximum Life",
            r"Spirit",
            r"Minion",
            r"Allies",
            r"Resistance",
            r"Attack Speed",
        ],
    },
    "weapon.bow": {
        "include": [
            r"Physical Damage",
            r"Fire Damage",
            r"Cold Damage",
            r"Lightning Damage",
            r"Chaos Damage",
            r"increased Attack Speed",
            r"Critical",
            r"added.*Damage",
            r"to (Strength|Dexterity|Intelligence|all Attributes)",
            r"Level of Socketed",
            r"Projectile",
            r"Bow",
        ],
        "exclude": [
            r"to maximum Life",
            r"Spirit",
            r"Minion",
            r"Allies",
            r"Resistance",
            r"Cast Speed",
            r"Energy Shield",
        ],
    },
    "weapon.oneaxe": {
        "include": [
            r"Physical Damage",
            r"Fire Damage",
            r"Cold Damage",
            r"Lightning Damage",
            r"increased Attack Speed",
            r"Critical",
            r"added.*Damage",
            r"to (Strength|Dexterity)",
            r"Level of Socketed",
        ],
        "exclude": [
            r"to maximum Life",
            r"Spirit",
            r"Minion",
            r"Allies",
            r"Resistance",
            r"Cast Speed",
            r"Energy Shield",
        ],
    },
    "weapon.onemace": {
        "include": [
            r"Physical Damage",
            r"Fire Damage",
            r"Cold Damage",
            r"Lightning Damage",
            r"increased Attack Speed",
            r"Critical",
            r"added.*Damage",
            r"to (Strength|Dexterity)",
            r"Level of Socketed",
        ],
        "exclude": [
            r"to maximum Life",
            r"Spirit",
            r"Minion",
            r"Allies",
            r"Resistance",
            r"Cast Speed",
            r"Energy Shield",
        ],
    },
    "weapon.onesword": {
        "include": [
            r"Physical Damage",
            r"Fire Damage",
            r"Cold Damage",
            r"Lightning Damage",
            r"increased Attack Speed",
            r"Critical",
            r"added.*Damage",
            r"to (Strength|Dexterity)",
            r"Level of Socketed",
        ],
        "exclude": [
            r"to maximum Life",
            r"Spirit",
            r"Minion",
            r"Allies",
            r"Resistance",
            r"Cast Speed",
            r"Energy Shield",
        ],
    },
    "weapon.claw": {
        "include": [
            r"Physical Damage",
            r"Fire Damage",
            r"Cold Damage",
            r"Lightning Damage",
            r"Chaos Damage",
            r"increased Attack Speed",
            r"Critical",
            r"added.*Damage",
            r"to (Strength|Dexterity|Intelligence)",
            r"Life Leech",
            r"Life.*Hit",
        ],
        "exclude": [
            r"to maximum Life",
            r"Spirit",
            r"Minion",
            r"Allies",
            r"Resistance",
            r"Cast Speed",
            r"Energy Shield",
        ],
    },
    "weapon.dagger": {
        "include": [
            r"Physical Damage",
            r"Fire Damage",
            r"Cold Damage",
            r"Lightning Damage",
            r"Chaos Damage",
            r"increased Attack Speed",
            r"Critical",
            r"added.*Damage",
            r"to (Strength|Dexterity|Intelligence)",
            r"Poison",
        ],
        "exclude": [
            r"to maximum Life",
            r"Spirit",
            r"Minion",
            r"Allies",
            r"Resistance",
            r"Cast Speed",
            r"Energy Shield",
        ],
    },
    "weapon.twosword": {
        "include": [
            r"Physical Damage",
            r"Fire Damage",
            r"Cold Damage",
            r"Lightning Damage",
            r"increased Attack Speed",
            r"Critical",
            r"added.*Damage",
            r"to (Strength|Dexterity)",
            r"Level of Socketed",
        ],
        "exclude": [
            r"to maximum Life",
            r"Spirit",
            r"Minion",
            r"Allies",
            r"Resistance",
            r"Cast Speed",
            r"Energy Shield",
        ],
    },
    "weapon.twoaxe": {
        "include": [
            r"Physical Damage",
            r"Fire Damage",
            r"Cold Damage",
            r"Lightning Damage",
            r"increased Attack Speed",
            r"Critical",
            r"added.*Damage",
            r"to (Strength|Dexterity)",
            r"Level of Socketed",
        ],
        "exclude": [
            r"to maximum Life",
            r"Spirit",
            r"Minion",
            r"Allies",
            r"Resistance",
            r"Cast Speed",
            r"Energy Shield",
        ],
    },
    "weapon.twomace": {
        "include": [
            r"Physical Damage",
            r"Fire Damage",
            r"Cold Damage",
            r"Lightning Damage",
            r"increased Attack Speed",
            r"Critical",
            r"added.*Damage",
            r"to (Strength|Dexterity)",
            r"Level of Socketed",
        ],
        "exclude": [
            r"to maximum Life",
            r"Spirit",
            r"Minion",
            r"Allies",
            r"Resistance",
            r"Cast Speed",
            r"Energy Shield",
        ],
    },
    "weapon.staff": {
        "include": [
            r"Physical Damage",
            r"Fire Damage",
            r"Cold Damage",
            r"Lightning Damage",
            r"Chaos Damage",
            r"increased Cast Speed",
            r"Critical",
            r"added.*Damage",
            r"to (Strength|Dexterity|Intelligence|all Attributes)",
            r"Level of all Spell",
            r"Spell Damage",
        ],
        "exclude": [
            r"to maximum Life",
            r"Spirit",
            r"Minion",
            r"Allies",
            r"Resistance",
            r"Attack Speed",
            r"Energy Shield",
        ],
    },
    "weapon.warstaff": {
        "include": [
            r"Physical Damage",
            r"Fire Damage",
            r"Cold Damage",
            r"Lightning Damage",
            r"increased Attack Speed",
            r"Critical",
            r"added.*Damage",
            r"to (Strength|Dexterity)",
            r"Level of Socketed",
        ],
        "exclude": [
            r"to maximum Life",
            r"Spirit",
            r"Minion",
            r"Allies",
            r"Resistance",
            r"Cast Speed",
            r"Energy Shield",
        ],
    },
    "weapon.crossbow": {
        "include": [
            r"Physical Damage",
            r"Fire Damage",
            r"Cold Damage",
            r"Lightning Damage",
            r"increased Attack Speed",
            r"Critical",
            r"added.*Damage",
            r"to (Strength|Dexterity)",
            r"Projectile",
            r"Level of Socketed",
        ],
        "exclude": [
            r"to maximum Life",
            r"Spirit",
            r"Minion",
            r"Allies",
            r"Resistance",
            r"Cast Speed",
            r"Energy Shield",
        ],
    },
    "armour.chest": {
        "include": [
            r"to maximum Life",
            r"to maximum Mana",
            r"to maximum Energy Shield",
            r"to Spirit",
            r"increased Spirit",
            r"Fire Resistance",
            r"Cold Resistance",
            r"Lightning Resistance",
            r"Chaos Resistance",
            r"all Elemental Resistances",
            r"to (Strength|Dexterity|Intelligence|all Attributes)",
            r"increased.*Armour",
            r"increased.*Evasion",
            r"increased.*Energy Shield",
            r"Life Regeneration",
        ],
        "exclude": [
            r"Minions deal",
            r"Minions have",
            r"Minions gain",
            r"Allies.*deal.*added",
            r"to Level of all",
            r"Cast Speed",
            r"Attack Speed",
            r"Movement Speed",
        ],
    },
    "armour.helmet": {
        "include": [
            r"to maximum Life",
            r"to maximum Mana",
            r"to maximum Energy Shield",
            r"Level of all Minion Skills",
            r"Fire Resistance",
            r"Cold Resistance",
            r"Lightning Resistance",
            r"Chaos Resistance",
            r"to (Strength|Dexterity|Intelligence|all Attributes)",
            r"increased.*Armour",
            r"increased.*Evasion",
            r"increased.*Energy Shield",
            r"increased Rarity",
        ],
        "exclude": [
            r"Minions deal",
            r"Minions have",
            r"Minions gain",
            r"Allies.*deal.*added",
            r"Allies.*have",
            r"Spirit",
            r"Cast Speed",
            r"Attack Speed",
            r"Movement Speed",
        ],
    },
    "armour.gloves": {
        "include": [
            r"to maximum Life",
            r"to maximum Mana",
            r"to maximum Energy Shield",
            r"increased Attack Speed",
            r"increased Cast Speed",
            r"Fire Resistance",
            r"Cold Resistance",
            r"Lightning Resistance",
            r"Chaos Resistance",
            r"to (Strength|Dexterity|Intelligence|all Attributes)",
            r"added.*Damage.*Attacks",
            r"increased.*Armour",
            r"increased.*Evasion",
            r"increased.*Energy Shield",
            r"increased Rarity",
        ],
        "exclude": [
            r"Minion",
            r"Allies",
            r"Spirit",
            r"to Level of all",
            r"Movement Speed",
        ],
    },
    "armour.boots": {
        "include": [
            r"to maximum Life",
            r"to maximum Mana",
            r"to maximum Energy Shield",
            r"increased Movement Speed",
            r"Fire Resistance",
            r"Cold Resistance",
            r"Lightning Resistance",
            r"Chaos Resistance",
            r"to (Strength|Dexterity|Intelligence|all Attributes)",
            r"increased.*Armour",
            r"increased.*Evasion",
            r"increased.*Energy Shield",
            r"increased Rarity",
        ],
        "exclude": [
            r"Minion",
            r"Allies",
            r"Spirit",
            r"to Level of all",
            r"Cast Speed",
            r"Attack Speed",
        ],
    },
    "armour.shield": {
        "include": [
            r"to maximum Life",
            r"to maximum Energy Shield",
            r"Fire Resistance",
            r"Cold Resistance",
            r"Lightning Resistance",
            r"Chaos Resistance",
            r"all Elemental Resistances",
            r"to (Strength|Dexterity|Intelligence|all Attributes)",
            r"increased.*Armour",
            r"increased.*Energy Shield",
            r"Block",
            r"Spell Damage",
            r"Cast Speed",
        ],
        "exclude": [
            r"Minion",
            r"Allies",
            r"Spirit",
            r"to Level of all",
            r"Movement Speed",
            r"Attack Speed",
        ],
    },
    "armour.quiver": {
        "include": [
            r"Physical Damage.*Attacks",
            r"added.*Damage.*Attacks",
            r"increased Attack Speed",
            r"Critical",
            r"to (Strength|Dexterity|Intelligence)",
            r"Projectile",
            r"Bow",
            r"Level of Socketed",
        ],
        "exclude": [
            r"to maximum Life",
            r"Spirit",
            r"Minion",
            r"Allies",
            r"Resistance",
            r"Cast Speed",
            r"Energy Shield",
        ],
    },
}


# ── Utility ──

def validate_stats_for_item(item_type: str | None, stat_groups: list) -> list:
    """Filter stat groups to only include stats available on the target item type.

    Args:
        item_type: Trade API item category (e.g. 'accessory.amulet'), or None
        stat_groups: List of resolved stat groups from parse_intent_ai

    Returns:
        Filtered stat groups. Stats that don't match item type rules are removed.
        Count groups with too few stats get count_min adjusted.
    """
    if not item_type or not stat_groups:
        return stat_groups

    rules = STAT_AVAILABILITY.get(item_type)
    if not rules:
        # No rules for this item type — allow all stats through
        return stat_groups

    includes = rules.get("include", [])
    excludes = rules.get("exclude", [])

    validated = []
    for group in stat_groups:
        group_type = group.get("type", "and")
        filtered = []

        for stat in group.get("stats", []):
            ref = stat.get("matched_ref", "")
            stat_id = stat.get("id", "")

            if not ref:
                # If no ref_text (shouldn't happen), keep the stat
                filtered.append(stat)
                continue

            # Check include rules first (if defined): explicit allowlist
            if includes:
                included = any(re.search(pat, ref, re.IGNORECASE) for pat in includes)
                if not included:
                    logger.info(
                        f"AVAILABILITY: Dropping '{ref[:50]}' ({stat_id}) — "
                        f"not in include list for {item_type}"
                    )
                    continue
                # If included, skip exclude check — include is explicit permission
            else:
                # No include list: use exclude list to block problematic stats
                excluded = False
                for pat in excludes:
                    if re.search(pat, ref, re.IGNORECASE):
                        logger.info(
                            f"AVAILABILITY: Dropping '{ref[:50]}' ({stat_id}) — "
                            f"excluded from {item_type} (pattern: {pat})"
                        )
                        excluded = True
                        break
                if excluded:
                    continue

            filtered.append(stat)

        # Build validated group
        if group_type == "and":
            # AND groups: ALL stats must survive, otherwise the whole group fails
            if len(filtered) == len(group.get("stats", [])):
                validated.append(group)
            else:
                logger.warning(
                    f"AVAILABILITY: Dropping entire AND group — "
                    f"{len(filtered)}/{len(group.get('stats', []))} stats survived"
                )
                # Keep the group with surviving stats but log the issue
                if filtered:
                    g = dict(group)
                    g["stats"] = filtered
                    validated.append(g)

        elif group_type == "count":
            if not filtered:
                logger.warning("AVAILABILITY: All stats dropped from count group")
                continue

            g = dict(group)
            g["stats"] = filtered
            count_min = g.get("count_min", 1)
            if count_min > len(filtered):
                new_min = max(1, len(filtered))
                logger.warning(
                    f"AVAILABILITY: Adjusting count_min {count_min}→{new_min} "
                    f"(only {len(filtered)} stats available on {item_type})"
                )
                g["count_min"] = new_min
            validated.append(g)

        elif group_type == "not":
            # NOT groups: always keep (excluding bad stats doesn't hurt)
            if filtered:
                g = dict(group)
                g["stats"] = filtered
                validated.append(g)

        else:  # weight2 or other
            if filtered:
                g = dict(group)
                g["stats"] = filtered
                validated.append(g)

    return validated


def inject_fallback_stats(
    db,
    stat_groups: list,
    item_type: str | None = None,
) -> list:
    """Inject universal stats into count groups that have too few members.

    After validation, a count group might only have 1-2 stats but need
    count_min=2. This adds universal stats (life, res) that exist on ALL
    item types to ensure count_min is achievable.

    Args:
        db: Database session
        stat_groups: Stat groups after validation
        item_type: Target item type (used to check which universals apply)

    Returns:
        Stat groups with universal fallbacks injected into count groups
    """
    from app.services.trade_service import _resolve_stat

    # Get universal stats applicable to this item type
    rules = STAT_AVAILABILITY.get(item_type, {}) if item_type else {}
    type_excludes = rules.get("exclude", [])
    applicable_universals = [
        s for s in UNIVERSAL_INCLUDE
        if not any(re.search(pat, s, re.IGNORECASE) for pat in type_excludes)
    ]

    for group in stat_groups:
        if group.get("type") != "count":
            continue

        current_count = len(group.get("stats", []))
        count_min = group.get("count_min", 1)
        # We want count_min + 2 spare for safety margin
        target_count = max(count_min + 2, 5)

        if current_count >= target_count:
            continue

        needed = target_count - current_count
        added = 0
        for fallback_text in applicable_universals:
            if added >= needed:
                break
            # Skip if already in the group
            existing_refs = [s.get("matched_ref", "") for s in group["stats"]]
            if any(fallback_text.lower() in ref.lower() for ref in existing_refs):
                continue

            # Resolve via vector search
            resolved = _resolve_stat(db, {
                "desc_en": fallback_text,
                "desc_zh": "",
            })
            if resolved:
                group["stats"].append(resolved)
                added += 1
                logger.info(
                    f"FALLBACK: Injected '{resolved['matched_ref'][:50]}' "
                    f"({resolved['id']}) into count group"
                )

        if added > 0:
            logger.info(
                f"FALLBACK: Added {added} universal stats to count group "
                f"(now {len(group['stats'])} stats, count_min={count_min})"
            )

    return stat_groups
