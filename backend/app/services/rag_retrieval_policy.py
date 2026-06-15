"""Unified RAG retrieval policy — detail vs catalog, not per-entity patches."""

from __future__ import annotations

import re
from typing import Literal

from app.services.retrieval_pipeline import RetrievalOptions

RetrievalIntent = Literal["detail", "catalog"]

# User wants enumeration / overview (升华列表、有哪些、对比多个)
_CATALOG_RE = re.compile(
    r"(有哪些|有什么|全部|列出|列举|几个|哪些|所有|一览|汇总|对比|比较|区别|"
    r"升华(技能|节点|点)|notable|passives?)",
    re.I,
)


def classify_retrieval_intent(user_msg: str) -> RetrievalIntent:
    text = (user_msg or "").strip()
    if not text:
        return "detail"
    if _CATALOG_RE.search(text):
        return "catalog"
    return "detail"


def retrieval_top_k(
    *,
    intent: RetrievalIntent,
    entity_types: set[str],
    fast: bool,
) -> int:
    """How many vector hits to keep — catalog / ascendancy need more chunks."""
    if intent == "catalog" or "ascendancy" in entity_types:
        return 14
    return 5 if fast else 6


def build_rag_options(
    *,
    user_msg: str,
    query: str,
    entities: list[tuple[str, str, str]],
    fast: bool,
    q_embedding: list[float],
    league: str | None,
    game_version: str | None,
    alias_keywords: list[str],
) -> tuple[RetrievalOptions, RetrievalIntent]:
    intent = classify_retrieval_intent(user_msg)
    entity_types = {etype for etype, _, _ in entities}
    return (
        RetrievalOptions(
            top_k=retrieval_top_k(intent=intent, entity_types=entity_types, fast=fast),
            classify_text=user_msg,
            q_embedding=q_embedding,
            league=league,
            game_version=game_version,
            alias_keywords=alias_keywords,
            expand_concepts=False,
            multi_source=not fast,
            per_source=3 if fast else 5,
        ),
        intent,
    )


def structured_fetch_mode(etype: str, intent: RetrievalIntent) -> Literal["single", "multi"]:
    """How many DB rows to return per resolved entity."""
    if intent == "catalog":
        return "multi"
    if etype == "ascendancy":
        return "multi"
    return "single"
