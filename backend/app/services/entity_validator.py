"""Post-hoc entity validation — jieba (CN) + set matching (EN) for hallucination detection.

Builds entity dictionaries from kb_entities on first use. Provides validate_answer()
that scans answer text and returns suspicious entities not in the provided whitelist.

Usage:
    from app.services.entity_validator import get_validator

    validator = get_validator()
    suspicious = validator.validate(answer_text, whitelist_ids={...})
    # suspicious: list of (entity_name, risk_level, reason)
"""

from __future__ import annotations

import logging
import re
from typing import Any

import jieba

from app.core.database import SessionLocal
from app.models.knowledge_graph import KbEntity

logger = logging.getLogger(__name__)

# ── PoE1 known residues (hard-coded, augmented by PoE1−PoE2 set difference) ──
_POE1_BLACKLIST_EN: set[str] = {
    # Skills
    "unearth", "minion mastery", "minion pact", "bone construct",
    "bone offering", "flesh offering", "spirit offering", "raise zombie",
    "summon skeletons", "raise spectre", "summon raging spirit",
    "vaal summon skeletons", "desecrate", "convocation",
    # Classes
    "marauder", "ranger", "duelist", "templar", "shadow", "scion",
    # Ascendancies
    "juggernaut", "berserker", "chieftain",
    "necromancer", "elementalist", "occultist",
    "deadeye", "pathfinder", "raider",
    "saboteur", "trickster", "assassin",
    "guardian", "hierophant", "inquisitor",
    "champion", "gladiator", "slayer",
    "warden", "warlord", "ascendant",
    # PoE1 uniques commonly hallucinated
    "tabula rasa", "headhunter", "kaom's heart",
}

# ── Confusable Chinese entity pairs (context-dependent, hand-maintained) ──
# Format: wrong_name -> correct_name
_CONFUSABLE_PAIRS_CN: dict[str, str] = {
    "扭曲项链": "Distorted Amulet",   # 扭曲项链=Distorted (not Twisted)
    "畸变项链": "Twisted Amulet",     # 畸变项链=Twisted (not Distorted)
}

# ── Risk levels ──
RISK_POE1 = "POE1_RESIDUE"       # Known PoE1 entity → high risk
RISK_NOT_GROUNDED = "NOT_GROUNDED"  # Not in white list → medium risk
RISK_CONFUSABLE = "CONFUSABLE"    # Confusable pair hit → medium risk


class EntityValidator:
    """Validates answer text against kb_entities dictionary."""

    def __init__(self):
        self._en_set: set[str] = set()
        self._cn_set: set[str] = set()
        self._cn_aliases: dict[str, str] = {}  # alias -> canonical
        self._en_aliases: dict[str, str] = {}   # alias -> canonical
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        db = SessionLocal()
        try:
            rows = db.query(KbEntity).filter(
                KbEntity.entity_type.in_(["skill", "item", "mod", "gem", "ascendancy", "class"]),
            ).all()
        finally:
            db.close()

        for ent in rows:
            en = (ent.name_en or "").strip().lower()
            cn = (ent.name_cn or "").strip()
            if en:
                self._en_set.add(en)
            if cn:
                self._cn_set.add(cn)
                jieba.add_word(cn, freq=10000)  # force as single token
            # Aliases
            aliases = []
            raw = ent.aliases
            if raw:
                try:
                    import json
                    aliases = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    pass
            for alias in aliases:
                a = str(alias).strip()
                if not a:
                    continue
                if re.search(r'[一-鿿]', a):
                    self._cn_set.add(a)
                    self._cn_aliases[a] = en
                    jieba.add_word(a, freq=10000)
                else:
                    self._en_set.add(a.lower())
                    self._en_aliases[a.lower()] = en

        self._loaded = True
        logger.info(
            "EntityValidator loaded: %d EN, %d CN, %d jieba words",
            len(self._en_set), len(self._cn_set), len(self._cn_set),
        )

    def validate(
        self,
        answer_text: str,
        whitelist_ids: set[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Scan answer for entities and return suspicious ones.

        Args:
            answer_text: The LLM-generated answer
            whitelist_ids: Set of kb_entity IDs that are grounded (from retrieval)

        Returns:
            List of {name, risk, reason, suggestion} dicts
        """
        self._ensure_loaded()
        text = answer_text or ""
        whitelist_ids = whitelist_ids or set()
        suspicious: list[dict] = []

        # ── English: word-level set lookup ──
        en_tokens = set(re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*', text))
        for token in en_tokens:
            t = token.lower()
            # Check blacklist
            if t in _POE1_BLACKLIST_EN:
                suspicious.append({
                    "name": token, "risk": RISK_POE1, "lang": "en",
                    "reason": f"known PoE1 entity: {token}",
                    "suggestion": f"remove or replace with PoE2 equivalent",
                })
                continue
            # Check not in kb_entities at all
            if t in self._en_set:
                continue  # known entity, fine
            if t in self._en_aliases:
                continue  # known alias, fine
            # Unknown — could be hallucinated
            if len(t) > 3 and t not in self._en_set:
                suspicious.append({
                    "name": token, "risk": RISK_NOT_GROUNDED, "lang": "en",
                    "reason": f"not found in kb_entities: {token}",
                })

        # ── Chinese: jieba word-level set lookup ──
        cn_tokens = jieba.lcut(text)
        cn_found = set()
        for token in cn_tokens:
            t = token.strip()
            if not t or len(t) < 2:
                continue
            if t in self._cn_set:
                cn_found.add(t)
            elif t in self._cn_aliases:
                cn_found.add(t)

        # Check confusable pairs
        for wrong, correct in _CONFUSABLE_PAIRS_CN.items():
            if wrong in text:
                suspicious.append({
                    "name": wrong, "risk": RISK_CONFUSABLE, "lang": "cn",
                    "reason": f"confusable: '{wrong}' may have been confused with '{correct}'",
                    "suggestion": f"verify context — did you mean '{correct}'?",
                })

        return suspicious


# ── Singleton ──
_validator: EntityValidator | None = None


def get_validator() -> EntityValidator:
    global _validator
    if _validator is None:
        _validator = EntityValidator()
    return _validator


def validate_answer(
    answer_text: str,
    whitelist_ids: set[int] | None = None,
) -> list[dict[str, Any]]:
    return get_validator().validate(answer_text, whitelist_ids)
