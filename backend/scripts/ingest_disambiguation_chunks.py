"""Ingest static FAQ disambiguation chunks (CN+EN)."""

import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.services.concept_links import compute_links
from app.services.embedding_service import get_embedding
from scripts.ingest_poe2db import content_hash

DISAMBIGUATION_CHUNKS = [
    {
        "chunk_id": "faq_skill_bar_vs_exceptional_gem",
        "search_text": (
            "FAQ: 技能栏位 vs 非凡宝石槽 / Skill Bar slots vs Exceptional Gem slots\n"
            "技能栏位 (Skill Bar slots) are the active skill gem slots on your character bar. "
            "非凡宝石槽 (Exceptional gem sockets) are special sockets on gear for Exceptional gems, "
            "not the same as extra Skill Bar slots. Do not confuse gem socket count with Skill Bar capacity."
        ),
    },
    {
        "chunk_id": "faq_augmented_flesh_skill_bar",
        "search_text": (
            "FAQ: Augmented Flesh / 强化之肉 grants Skill Bar slots\n"
            "Unique item Augmented Flesh (强化之肉) grants 2 additional Skill Bar slots. "
            "This is a body armour unique effect, not an exceptional gem socket."
        ),
    },
    {
        "chunk_id": "faq_twisted_vs_distorted_amulet",
        "search_text": (
            "FAQ: Twisted Amulet vs Distorted Amulet / 畸变项链 vs 扭曲项链\n"
            "[CN Official] 扭曲项链 = Distorted Amulet (Trade API base type). "
            "[CN Official] 畸变项链 = Twisted Amulet (Delirium instilled-notable base). "
            "Community slang 扭曲护身符 often means Twisted Amulet (涂油/Instilled Notables), "
            "NOT the same as 扭曲项链 Distorted Amulet. "
            "When user asks 扭曲项链词条, answer Distorted Amulet affix pool unless they "
            "clearly mean Delirium instilling / 涂油 / Instilled Notables."
        ),
    },
    {
        "chunk_id": "faq_twisted_amulet_instilled",
        "search_text": (
            "FAQ: Twisted Amulet / 畸变项链 Instilled Notables\n"
            "Twisted Amulet (畸变项链) can be Instilled to gain random Instilled Notables on the amulet. "
            "Instilled Notables are special passive-like bonuses from the Instilling mechanic (涂油/instill). "
            "See Instilled Notables list for possible outcomes. "
            "Do NOT confuse with Distorted Amulet (扭曲项链), a different base type."
        ),
    },
    {
        "chunk_id": "faq_chenmo_mjolner",
        "search_text": (
            "FAQ: 沉默之雷 = Mjölner (CN official name)\n"
            "[CN] 沉默之雷 is the Tencent/国服 name for the unique Mjölner (EN), base Torment Club / 劫难战棒. "
            "Do NOT translate 沉默之雷 as Silence Thunder or Silent Thunder. "
            "Grants Level 18 Wrath of the Thunder God / 雷霆神祇之怒 (triggered lightning spell socket skill). "
            "Explicit mods include increased Physical Damage, +Strength/+Intelligence requirements, "
            "+2 to +4 to Level of all Lightning Skills, increased Attack Speed."
        ),
    },
    {
        "chunk_id": "faq_instilling_mechanic",
        "search_text": (
            "FAQ: Instilling / 涂油 mechanic overview\n"
            "Instilling applies Instilled Notables onto eligible jewellery using Instilling items. "
            "Each Instilled Notable adds a notable-like modifier."
        ),
    },
    {
        "chunk_id": "faq_skill_bar_capacity",
        "search_text": (
            "FAQ: 技能栏位 capacity / Skill Bar slots\n"
            "Base characters have a fixed Skill Bar slot count; some uniques (e.g. Augmented Flesh) "
            "grant additional Skill Bar slots explicitly."
        ),
    },
    {
        "chunk_id": "faq_exceptional_gems",
        "search_text": (
            "FAQ: Exceptional gems / 非凡宝石\n"
            "Exceptional gems fit Exceptional gem sockets on gear. They do not automatically add Skill Bar slots."
        ),
    },
    {
        "chunk_id": "faq_mjolner_name",
        "search_text": (
            "FAQ: Mjölner / 沉默之雷 naming\n"
            "EN: Mjölner. CN: 沉默之雷. Base: Torment Club (劫难战棒). "
            "Invalid scraped glue names like MjölnerTorment Club must map to Mjölner only."
        ),
    },
    {
        "chunk_id": "faq_twisted_amulet_bases",
        "search_text": (
            "FAQ: Twisted Amulet bases\n"
            "Twisted Amulet refers to Delirium twisted amulet bases; instilled notables vary by roll."
        ),
    },
    {
        "chunk_id": "faq_cn_en_skill_bar",
        "search_text": (
            "FAQ CN/EN: 技能栏位 = Skill Bar slots\n"
            "When users ask 几个技能栏 or 技能栏位, they mean Skill Bar slots, not weapon gem sockets."
        ),
    },
]


def ingest(league: str | None = None, game_version: str | None = None) -> None:
    db = SessionLocal()
    source = "faq"
    try:
        existing = set()
        for (content,) in db.query(KnowledgeChunk.content).filter(
            KnowledgeChunk.source == source,
        ).all():
            try:
                existing.add(content_hash(json.loads(content).get("search_text", "")[:2000]))
            except Exception:
                existing.add(content_hash(content[:2000]))

        ingested = skipped = failed = 0
        for chunk in DISAMBIGUATION_CHUNKS:
            search_text = chunk["search_text"][:2000]
            chash = content_hash(search_text)
            if chash in existing:
                skipped += 1
                continue
            payload = {
                "search_text": search_text,
                "content_type": "wiki",
                "chunk_id": chunk["chunk_id"],
            }
            embedding = get_embedding(search_text)
            if not embedding:
                failed += 1
                continue
            links = compute_links(search_text, "wiki")
            kc = KnowledgeChunk(
                content=json.dumps(payload, ensure_ascii=False),
                embedding=embedding,
                source=source,
                chunk_type="wiki",
                links=json.dumps(links, ensure_ascii=False) if links else None,
                league=league,
                game_version=game_version,
            )
            db.add(kc)
            existing.add(chash)
            ingested += 1
        db.commit()
        logger.info("Done: %d added, %d skipped, %d failed", ingested, skipped, failed)
    finally:
        db.close()


if __name__ == "__main__":
    ingest()
