from __future__ import annotations

"""Post-hoc entity validation with evidence grounding.

Pattern (inspired by AgentClaimGuard):
    Claim (entity in answer) → Evidence (entity in retrieval chunks?) → Verdict
        ├── in PoE1 blacklist → REJECT (POE1_RESIDUE)
        ├── in evidence chunks → PASS (GROUNDED)
        ├── in confusable pairs → WARN (CONGURABLE)
        └── not in evidence     → WARN (NOT_GROUNDED)

Key difference from v1: entities that appear in the retrieval results are
considered grounded — no more false positives like "Rattling Sceptre".
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── Common English words that start with uppercase but aren't entities ──
_COMMON_FALSE_POSITIVES: set[str] = {
    "intelligence", "strength", "dexterity", "spirit", "life", "mana",
    "boss", "curse", "aura", "buff", "debuff", "minion", "totem",
    "weapon", "armour", "armor", "shield", "helmet", "gloves", "boots",
    "ring", "amulet", "belt", "flask", "quiver", "crossbow", "bow", "wand",
    "sceptre", "staff", "sword", "axe", "mace", "dagger", "claw",
    "fire", "cold", "lightning", "chaos", "physical", "elemental",
    "poison", "bleed", "ignite", "freeze", "shock", "stun",
    "critical", "attack", "spell", "cast", "damage", "resistance",
    "tier", "level", "skill", "support", "gem", "socket", "link",
    "ascendancy", "passive", "notable", "keystone", "cluster",
    "map", "waystone", "breach", "delirium", "ritual", "expedition",
    "unique", "rare", "magic", "normal",
    "offering", "offering",  # common skill word, not a specific entity
}

logger = logging.getLogger(__name__)

# ── PoE1 known residues ──
_POE1_BLACKLIST_EN: set[str] = {
    "unearth", "minion mastery", "minion pact", "minion pact ii",
    "bone construct", "bone offering", "flesh offering", "spirit offering",
    "raise zombie", "summon skeletons", "raise spectre", "summon raging spirit",
    "vaal summon skeletons", "desecrate", "convocation",
    "marauder", "ranger", "duelist", "templar", "shadow", "scion",
    "juggernaut", "berserker", "chieftain",
    "necromancer", "elementalist", "occultist",
    "deadeye", "pathfinder", "raider",
    "saboteur", "trickster", "assassin",
    "guardian", "hierophant", "inquisitor",
    "champion", "gladiator", "slayer",
    "warden", "warlord", "ascendant",
    "tabula rasa", "headhunter", "kaom's heart",
    "pain offering", "soul offering", "bone offering",
    "flesh offering", "spirit offering", "carrion golem",
    "stone golem", "chaos golem", "lightning golem", "flame golem", "ice golem",
}

# ── Confusable pairs (hand-maintained) ──
_CONFUSABLE_EN: dict[str, str] = {
    "twisted amulet": "Distorted Amulet",   # 扭曲项链 ≠ Twisted Amulet
    "distorted amulet": "Twisted Amulet",    # 畸变项链 ≠ Distorted Amulet
}

# ── Risk levels ──
RISK_POE1 = "POE1_RESIDUE"
RISK_NOT_GROUNDED = "NOT_GROUNDED"
RISK_NOT_IN_GAME_DATA = "NOT_IN_GAME_DATA"
RISK_CONFUSABLE = "CONFUSABLE"


# ── English entity extraction ──
_WORD_RE = re.compile(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b')


def _extract_en_entities(text: str) -> set[str]:
    """Extract likely English entity names from text."""
    return {m.group(0).lower() for m in _WORD_RE.finditer(text)}


# ── Chinese entity extraction ──
_jieba_loaded = False


def _ensure_jieba():
    global _jieba_loaded
    if _jieba_loaded:
        return
    import jieba
    # Register known PoE2 Chinese entity names as jieba words
    from app.core.database import SessionLocal
    from app.models.knowledge_graph import KbEntity
    db = SessionLocal()
    try:
        rows = db.query(KbEntity.name_cn).filter(
            KbEntity.name_cn.isnot(None),
            KbEntity.name_cn != "",
            KbEntity.entity_type.in_(["skill", "item", "gem", "ascendancy", "class", "mod"]),
        ).distinct().all()
        for (cn,) in rows:
            if cn and len(cn) >= 2:
                jieba.add_word(cn, freq=10000)
    finally:
        db.close()
    _jieba_loaded = True
    logger.info("EntityValidator jieba dictionary loaded")


def _extract_cn_entities(text: str) -> set[str]:
    """Extract Chinese entity names from text using jieba."""
    _ensure_jieba()
    import jieba
    tokens = jieba.lcut(text)
    return {t.strip() for t in tokens if len(t.strip()) >= 2 and re.search(r'[一-鿿]', t)}


# ── GameGraph cross-check ──

def _check_game_graph(name: str) -> str | None:
    """Check if an entity name exists in GameGraph.

    Returns:
        Chinese name if found, "not_found" if not in GameGraph, None if GameGraph unavailable.
    """
    try:
        from app.services.game_graph_service import get_game_graph
        gg = get_game_graph()
        if gg is None:
            return None
        results = gg.find_entity(name)
        if not results:
            return "not_found"
        # Return the Chinese name of the first match
        table, key, _, _ = results[0]
        info = gg.entity_index.get((table, key), {})
        return info.get("name_sc") or info.get("name_en") or "found"
    except Exception:
        return None


# ── Main validation ──

def validate_answer(
    answer_text: str,
    evidence_texts: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Validate entities in answer against evidence and blacklists.

    Args:
        answer_text: The LLM-generated answer
        evidence_texts: Full text of all retrieval chunks (the "ground truth" for this turn)

    Returns:
        List of {name, risk, reason} for suspicious entities
    """
    text = answer_text or ""
    evidence_lower = [e.lower() for e in (evidence_texts or [])]

    suspicious: list[dict] = []

    # ── English entities ──
    en_entities = _extract_en_entities(text)
    for name in sorted(en_entities, key=len, reverse=True):  # longest first
        nl = name.lower()

        # Skip common game terms that aren't specific entities
        if nl in _COMMON_FALSE_POSITIVES:
            continue
        # Check if in evidence — if so, skip (grounded)
        if _entity_in_evidence(nl, evidence_lower):
            continue

        # Check PoE1 blacklist
        if nl in _POE1_BLACKLIST_EN:
            suspicious.append({
                "name": name, "risk": RISK_POE1, "lang": "en",
                "reason": f"known PoE1 entity: {name}",
            })
            continue

        # Check confusable
        if nl in _CONFUSABLE_EN:
            suspicious.append({
                "name": name, "risk": RISK_CONFUSABLE, "lang": "en",
                "reason": f"may confuse with {_CONFUSABLE_EN[nl]}",
            })
            continue

        # Check evidence grounding
        if not _entity_in_evidence(nl, evidence_lower):
            # Cross-check against GameGraph (119k entities)
            gg_result = _check_game_graph(nl)
            if gg_result == "not_found":
                suspicious.append({
                    "name": name, "risk": RISK_NOT_IN_GAME_DATA, "lang": "en",
                    "reason": f"not in retrieval evidence AND not in GameGraph (119k entities)",
                })
            elif gg_result and gg_result != "found":
                suspicious.append({
                    "name": name, "risk": RISK_NOT_GROUNDED, "lang": "en",
                    "reason": f"not found in retrieval evidence",
                    "game_graph_cn": gg_result,
                })
            else:
                suspicious.append({
                    "name": name, "risk": RISK_NOT_GROUNDED, "lang": "en",
                    "reason": f"not found in retrieval evidence",
                })

    # ── Chinese entities ──
    cn_entities = _extract_cn_entities(text)
    for name in cn_entities:
        # Check confusable pairs for Chinese
        for wrong, correct in _CONFUSABLE_EN.items():
            if wrong.lower() in text.lower() and name.lower() in wrong.lower():
                suspicious.append({
                    "name": name, "risk": RISK_CONFUSABLE, "lang": "cn",
                    "reason": f"confusable CN term, verify context",
                })

    return suspicious


def _entity_in_evidence(name_lower: str, evidence_lower: list[str]) -> bool:
    """Check if an entity name appears in any evidence chunk."""
    for ev in evidence_lower:
        if name_lower in ev:
            return True
    return False
